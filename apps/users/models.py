import hashlib
import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

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
    phone = models.CharField(max_length=20, blank=True, db_column='usr_telefone')
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
    id = models.BigAutoField(primary_key=True, db_column='tfa_id')
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='two_factor_config',
        db_column='tfa_usuario_id',
    )
    secret = models.CharField(max_length=64, db_column='tfa_secret')
    is_active = models.BooleanField(default=False, db_column='tfa_ativo')
    backup_codes = models.JSONField(default=list, db_column='tfa_backup_codes')
    created_at = models.DateTimeField(auto_now_add=True, db_column='tfa_criado_em')
    updated_at = models.DateTimeField(auto_now=True, db_column='tfa_atualizado_em')

    class Meta:
        db_table = 'configs_2fa'

    def verify_totp_or_backup(self, code: str) -> bool:
        """Verifica TOTP ou backup code. Consome o backup code se usado."""
        import pyotp
        code = code.strip().replace(' ', '').replace('-', '')
        totp = pyotp.TOTP(self.secret)
        if totp.verify(code, valid_window=1):
            return True
        # Tenta backup code (aceita com e sem hífen)
        raw_with_dash = f'{code[:4]}-{code[4:]}' if len(code) == 8 else code
        for candidate in (code, raw_with_dash):
            candidate_hash = hashlib.sha256(candidate.encode()).hexdigest()
            if candidate_hash in self.backup_codes:
                self.backup_codes = [h for h in self.backup_codes if h != candidate_hash]
                self.save(update_fields=['backup_codes', 'updated_at'])
                return True
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
