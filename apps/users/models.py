import hashlib
import hmac as hmac_module
import secrets
import string
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from .fields import EncryptedCharField


class TOTPLocked(Exception):
    """Lançada quando a verificação TOTP está bloqueada por excesso de tentativas."""
    pass

_BACKUP_CODE_ALPHABET = string.ascii_uppercase + string.digits


def generate_backup_codes(count: int = 8) -> list[str]:
    """Gera códigos de backup no formato XXXX-XXXX."""
    return [
        ''.join(secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(4))
        + '-'
        + ''.join(secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(4))
        for _ in range(count)
    ]


class User(AbstractUser):
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    PLAN_FREE = 'free'
    PLAN_PRO = 'pro'
    PLAN_CHOICES = [(PLAN_FREE, 'Free'), (PLAN_PRO, 'Pro')]

    email = models.EmailField(unique=True)

    plan = models.CharField(
        max_length=10, choices=PLAN_CHOICES, default=PLAN_FREE,
        db_column='usr_plano',
    )
    phone = models.CharField(max_length=20, blank=True, null=True, unique=True, db_column='usr_telefone')
    phone_verified = models.BooleanField(default=False, db_column='usr_tel_verificado')
    avatar_url = models.URLField(blank=True, db_column='usr_avatar_url')
    notif_cobracas = models.BooleanField(default=True, db_column='usr_notif_cobracas')
    notif_confirmacoes = models.BooleanField(default=True, db_column='usr_notif_confirmacoes')
    notif_lembretes = models.BooleanField(default=True, db_column='usr_notif_lembretes')

    class Meta:
        db_table = 'usuarios'


class NotificacaoLida(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='ntf_id')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notificacoes_lidas',
        db_column='ntf_usuario_id',
    )
    evento_id = models.CharField(max_length=60, db_column='ntf_evento_id')
    lida_em = models.DateTimeField(auto_now_add=True, db_column='ntf_lida_em')

    class Meta:
        db_table = 'notificacoes_lidas'
        unique_together = ('usuario', 'evento_id')

    def __str__(self):
        return f'{self.usuario_id} leu {self.evento_id}'


class TwoFactorConfig(models.Model):
    _LOCKOUT_THRESHOLD_SOFT = 5    # 5 falhas → 5 min
    _LOCKOUT_THRESHOLD_HARD = 10   # 10 falhas → 1 hora

    id = models.BigAutoField(primary_key=True, db_column='tfa_id')
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='two_factor_config',
        db_column='tfa_usuario_id',
    )
    secret = EncryptedCharField(max_length=512, db_column='tfa_secret')
    is_active = models.BooleanField(default=False, db_column='tfa_ativo')
    backup_codes = models.JSONField(default=list, db_column='tfa_backup_codes')
    # Proteção anti-replay: contador da última janela TOTP aceita (-1 = nunca)
    last_otp_counter = models.BigIntegerField(default=-1, db_column='tfa_last_otp_counter')
    # Rate limiting por config (não apenas por IP)
    otp_fail_count = models.IntegerField(default=0, db_column='tfa_otp_fail_count')
    otp_locked_until = models.DateTimeField(null=True, blank=True, db_column='tfa_otp_locked_until')
    created_at = models.DateTimeField(auto_now_add=True, db_column='tfa_criado_em')
    updated_at = models.DateTimeField(auto_now=True, db_column='tfa_atualizado_em')

    class Meta:
        db_table = 'configs_2fa'

    def verify_totp_or_backup(self, code: str) -> bool:
        """Verifica TOTP (com anti-replay) ou backup code (constant-time).

        Lança TOTPLocked se bloqueado por excesso de tentativas.
        Retorna True em caso de sucesso, False em caso de falha.
        Backup codes são consumidos (removidos) na primeira utilização.
        """
        import pyotp

        # 1. Lockout check
        if self.otp_locked_until and self.otp_locked_until > timezone.now():
            raise TOTPLocked()

        code = code.strip().replace(' ', '').replace('-', '')

        # 2. TOTP com anti-replay e constant-time compare
        totp = pyotp.TOTP(self.secret)
        counter = int(time.time() // 30)
        matched_counter = None

        for delta in (-1, 0, 1):
            c = counter + delta
            expected = totp.at(c * 30)
            if len(code) == len(expected) and hmac_module.compare_digest(code, expected):
                matched_counter = c
                break

        if matched_counter is not None:
            # Update atômico: só atualiza se o banco ainda NÃO tem este counter.
            # Previne replay em race condition (TOCTOU): dois requests concorrentes
            # passariam o check em memória, mas apenas um ganha o UPDATE no banco.
            updated = type(self).objects.filter(pk=self.pk).exclude(
                last_otp_counter=matched_counter,
            ).update(
                last_otp_counter=matched_counter,
                otp_fail_count=0,
                otp_locked_until=None,
            )
            if updated == 0:
                return False  # replay: counter já foi aceito (inclui race condition)
            self.last_otp_counter = matched_counter
            self.otp_fail_count = 0
            self.otp_locked_until = None
            return True

        # 3. Backup codes — constant-time compare contra cada hash armazenado
        code_dash = f'{code[:4]}-{code[4:]}' if len(code) == 8 else code
        h_plain = hashlib.sha256(code.encode()).hexdigest()
        h_dash = hashlib.sha256(code_dash.encode()).hexdigest()

        matched_hash = None
        for stored_hash in self.backup_codes:
            m1 = secrets.compare_digest(stored_hash, h_plain)
            m2 = secrets.compare_digest(stored_hash, h_dash)
            if (m1 | m2) and matched_hash is None:  # | avalia os dois lados (sem short-circuit)
                matched_hash = stored_hash

        if matched_hash:
            self.backup_codes = [
                h for h in self.backup_codes
                if not secrets.compare_digest(h, matched_hash)
            ]
            type(self).objects.filter(pk=self.pk).update(
                backup_codes=self.backup_codes,
                otp_fail_count=0,
                otp_locked_until=None,
            )
            self.otp_fail_count = 0
            self.otp_locked_until = None
            return True

        # 4. Falha — incrementa tentativas atomicamente e aplica lockout
        type(self).objects.filter(pk=self.pk).update(
            otp_fail_count=models.F('otp_fail_count') + 1,
        )
        self.refresh_from_db(fields=['otp_fail_count'])
        fail_count = self.otp_fail_count

        if fail_count >= self._LOCKOUT_THRESHOLD_HARD:
            lockout_until = timezone.now() + timedelta(hours=1)
            type(self).objects.filter(pk=self.pk).update(otp_locked_until=lockout_until)
        elif fail_count >= self._LOCKOUT_THRESHOLD_SOFT:
            lockout_until = timezone.now() + timedelta(minutes=5)
            type(self).objects.filter(pk=self.pk).update(otp_locked_until=lockout_until)

        return False


class TrustedDevice(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='trd_id')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='trusted_devices',
        db_column='trd_usuario_id',
    )
    token_hash = models.CharField(max_length=64, db_column='trd_token_hash')
    user_agent = models.CharField(max_length=256, blank=True, db_column='trd_user_agent')
    expires_at = models.DateTimeField(db_column='trd_expires_at')
    last_used_at = models.DateTimeField(null=True, blank=True, db_column='trd_ultimo_uso')
    created_at = models.DateTimeField(auto_now_add=True, db_column='trd_criado_em')

    class Meta:
        db_table = 'dispositivos_confiaveis'
        indexes = [models.Index(fields=['user', 'token_hash', 'expires_at'])]


class PasswordResetCode(models.Model):
    MAX_ATTEMPTS = 5
    CODE_TTL_MINUTES = 20

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reset_codes',
        db_column='prc_usuario_id',
    )
    code_hash = models.CharField(max_length=64, db_column='prc_code_hash')
    expires_at = models.DateTimeField(db_column='prc_expires_at')
    used = models.BooleanField(default=False, db_column='prc_usado')
    attempts = models.PositiveSmallIntegerField(default=0, db_column='prc_tentativas')
    created_at = models.DateTimeField(auto_now_add=True, db_column='prc_criado_em')

    class Meta:
        db_table = 'codigos_recuperacao'
        indexes = [models.Index(fields=['user', 'used', 'expires_at'])]

    @classmethod
    def generate(cls, user) -> str:
        """Invalida códigos anteriores e cria um novo. Retorna o código em texto."""
        cls.objects.filter(user=user).delete()
        code = f'{secrets.randbelow(1_000_000):06d}'
        cls.objects.create(
            user=user,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=cls.CODE_TTL_MINUTES),
        )
        return code

    def is_valid(self) -> bool:
        return not self.used and self.attempts < self.MAX_ATTEMPTS and self.expires_at > timezone.now()

    def verify_and_consume(self, code: str) -> bool:
        """Consome o código se correto; incrementa tentativas atomicamente caso contrário."""
        submitted = hashlib.sha256(code.encode()).hexdigest()
        if secrets.compare_digest(self.code_hash, submitted):
            self.used = True
            self.save(update_fields=['used'])
            return True
        PasswordResetCode.objects.filter(pk=self.pk).update(attempts=models.F('attempts') + 1)
        return False


class SmsVerification(models.Model):
    MAX_ATTEMPTS = 5
    CODE_TTL_MINUTES = 10

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sms_verification',
        db_column='sms_usuario_id',
    )
    code_hash = models.CharField(max_length=64, db_column='sms_code_hash')
    expires_at = models.DateTimeField(db_column='sms_expires_at')
    used = models.BooleanField(default=False, db_column='sms_usado')
    attempts = models.PositiveSmallIntegerField(default=0, db_column='sms_tentativas')
    created_at = models.DateTimeField(auto_now_add=True, db_column='sms_criado_em')

    class Meta:
        db_table = 'verificacoes_sms'

    @classmethod
    def generate(cls, user) -> str:
        cls.objects.filter(user=user).delete()
        code = f'{secrets.randbelow(1_000_000):06d}'
        cls.objects.create(
            user=user,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=cls.CODE_TTL_MINUTES),
        )
        return code

    def is_valid(self) -> bool:
        return not self.used and self.attempts < self.MAX_ATTEMPTS and self.expires_at > timezone.now()

    def verify_and_consume(self, code: str) -> bool:
        submitted = hashlib.sha256(code.encode()).hexdigest()
        if secrets.compare_digest(self.code_hash, submitted):
            self.used = True
            self.save(update_fields=['used'])
            return True
        SmsVerification.objects.filter(pk=self.pk).update(attempts=models.F('attempts') + 1)
        return False


class AuditLog(models.Model):
    LOGIN_OK = 'login_ok'
    LOGIN_FAIL = 'login_fail'
    TOTP_OK = 'totp_ok'
    TOTP_FAIL = 'totp_fail'
    TOTP_LOCKED = 'totp_locked'
    TWO_FA_ON = '2fa_on'
    TWO_FA_OFF = '2fa_off'
    PWD_RESET = 'pwd_reset'
    TOKEN_REFRESH = 'token_refresh'
    DEBT_UPDATED = 'debt_updated'
    DEBT_DELETED = 'debt_deleted'

    EVENT_CHOICES = [
        (LOGIN_OK, 'Login bem-sucedido'),
        (LOGIN_FAIL, 'Login falhou'),
        (TOTP_OK, 'TOTP verificado'),
        (TOTP_FAIL, 'TOTP falhou'),
        (TOTP_LOCKED, 'TOTP bloqueado'),
        (TWO_FA_ON, '2FA ativado'),
        (TWO_FA_OFF, '2FA desativado'),
        (PWD_RESET, 'Senha redefinida'),
        (TOKEN_REFRESH, 'Token atualizado'),
        (DEBT_UPDATED, 'Dívida editada'),
        (DEBT_DELETED, 'Dívida excluída'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        db_column='aud_usuario_id',
        related_name='audit_logs',
    )
    event = models.CharField(max_length=20, choices=EVENT_CHOICES, db_column='aud_evento')
    ip = models.GenericIPAddressField(null=True, blank=True, db_column='aud_ip')
    user_agent = models.CharField(max_length=256, blank=True, db_column='aud_user_agent')
    detail = models.JSONField(default=dict, blank=True, db_column='aud_detalhe')
    created_at = models.DateTimeField(auto_now_add=True, db_column='aud_criado_em')

    class Meta:
        db_table = 'auditoria'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at'], name='auditoria_usr_idx'),
            models.Index(fields=['event', '-created_at'], name='auditoria_evt_idx'),
            models.Index(fields=['ip', '-created_at'], name='auditoria_ip_idx'),
        ]
