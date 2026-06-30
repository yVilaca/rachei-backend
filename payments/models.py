import uuid
from django.db import models
from django.utils import timezone


class ChargeLink(models.Model):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False,
        db_column='lnk_id',
    )
    installment = models.OneToOneField(
        'debts.Installment', on_delete=models.CASCADE, related_name='charge_link',
        db_column='lnk_parcela_id',
    )
    token = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False,
        db_column='lnk_token',
    )
    expires_at = models.DateTimeField(db_column='lnk_expira_em')
    used_at = models.DateTimeField(null=True, blank=True, db_column='lnk_usado_em')
    created_at = models.DateTimeField(auto_now_add=True, db_column='lnk_criado_em')

    class Meta:
        db_table = 'links_cobranca'

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f'Link de cobrança para parcela {self.installment_id}'
