import uuid
from django.db import models
from django.utils import timezone


class ChargeLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    installment = models.OneToOneField(
        'debts.Installment', on_delete=models.CASCADE, related_name='charge_link'
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'charge_links'

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f'ChargeLink for installment {self.installment_id}'
