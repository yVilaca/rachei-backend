from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    PLAN_FREE = 'free'
    PLAN_PRO = 'pro'
    PLAN_CHOICES = [(PLAN_FREE, 'Free'), (PLAN_PRO, 'Pro')]

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
