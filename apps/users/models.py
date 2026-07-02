import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


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
