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
