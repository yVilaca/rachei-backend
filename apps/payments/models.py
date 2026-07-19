import uuid
from django.conf import settings
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


class Acerto(models.Model):
    """
    Proposta de compensação (netting) entre duas pessoas. `de` propõe; `para`
    confirma. Ao confirmar, as dívidas pendentes entre os dois (nos dois sentidos)
    são compensadas e sobra apenas a dívida líquida.
    """
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Aguardando confirmação'),
        (STATUS_CONFIRMED, 'Confirmado'),
        (STATUS_REJECTED, 'Rejeitado'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column='act_id')
    de = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='acertos_propostos', db_column='act_de_id',
    )
    para = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='acertos_recebidos', db_column='act_para_id',
    )
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING,
        db_index=True, db_column='act_status',
    )
    parcelas = models.ManyToManyField(
        'debts.Installment', related_name='acertos', db_table='acerto_parcelas',
        blank=True,
    )
    # Parcelas efetivamente quitadas por esta compensação (trilha de auditoria).
    parcelas_quitadas = models.ManyToManyField(
        'debts.Installment', related_name='quitacoes_acerto',
        db_table='acerto_parcelas_quitadas', blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_column='act_criado_em')
    resolved_at = models.DateTimeField(null=True, blank=True, db_column='act_resolvido_em')

    class Meta:
        db_table = 'acertos'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['para', 'status'], name='acerto_para_status_idx'),
        ]

    def __str__(self):
        return f'Acerto {self.de_id}→{self.para_id} ({self.status})'


class Comprovante(models.Model):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False,
        db_column='cpv_id',
    )
    parcela = models.ForeignKey(
        'debts.Installment', on_delete=models.CASCADE, related_name='comprovantes',
        db_column='cpv_parcela_id',
    )
    file_url = models.URLField(db_column='cpv_arquivo_url')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='comprovantes_enviados',
        db_column='cpv_enviado_por_id',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, db_column='cpv_enviado_em')

    class Meta:
        db_table = 'comprovantes'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'Comprovante de {self.uploaded_by} para parcela {self.parcela_id}'
