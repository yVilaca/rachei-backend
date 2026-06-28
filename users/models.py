from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user — extends AbstractUser to allow future fields without migrations."""

    PLAN_FREE = 'free'
    PLAN_PRO = 'pro'
    PLAN_CHOICES = [(PLAN_FREE, 'Free'), (PLAN_PRO, 'Pro')]

    plan = models.CharField(max_length=10, choices=PLAN_CHOICES, default=PLAN_FREE)

    class Meta:
        db_table = 'users'
