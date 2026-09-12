import uuid
from django.conf import settings
from django.db import models


class Debt(models.Model):
    SPLIT_EQUAL = 'equal'
    SPLIT_CUSTOM = 'custom'
    SPLIT_CHOICES = [(SPLIT_EQUAL, 'Equal'), (SPLIT_CUSTOM, 'Custom')]

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False,
        db_column='dsp_id',
    )
    group = models.ForeignKey(
        'groups.Group', on_delete=models.CASCADE, related_name='debts',
        db_column='dsp_grupo_id',
    )
    description = models.CharField(max_length=255, db_column='dsp_descricao')
    total_amount_cents = models.PositiveIntegerField(db_column='dsp_total_centavos')
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='debts_paid',
        db_column='dsp_pago_por_id',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='debts_created',
        db_column='dsp_criado_por_id',
    )
    split_type = models.CharField(
        max_length=10, choices=SPLIT_CHOICES, default=SPLIT_EQUAL,
        db_column='dsp_tipo_divisao',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_column='dsp_criado_em')

    class Meta:
        db_table = 'despesas'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.description} ({self.group})'


class Installment(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_AWAITING = 'awaiting_confirmation'
    STATUS_PAID = 'paid'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pendente'),
        (STATUS_AWAITING, 'Aguardando confirmação'),
        (STATUS_PAID, 'Pago'),
    ]

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False,
        db_column='pcl_id',
    )
    debt = models.ForeignKey(
        Debt, on_delete=models.CASCADE, related_name='installments',
        db_column='pcl_despesa_id',
    )
    # Devedor: um usuário registrado OU um contato pendente (convidado por
    # telefone, ainda sem conta). Exatamente um dos dois é preenchido. Ao o
    # contato verificar o telefone (OTP), a parcela migra para o usuário real.
    debtor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='installments_owed',
        db_column='pcl_devedor_id',
    )
    debtor_contato = models.ForeignKey(
        'groups.ContatoPendente',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='parcelas',
        db_column='pcl_devedor_contato_id',
    )
    amount_cents = models.PositiveIntegerField(db_column='pcl_valor_centavos')
    status = models.CharField(
        max_length=25, choices=STATUS_CHOICES, default=STATUS_PENDING,
        db_column='pcl_status', db_index=True,
    )
    PAID_VIA_PAYMENT = 'payment'
    PAID_VIA_COMPENSATION = 'compensation'
    PAID_VIA_CHOICES = [
        (PAID_VIA_PAYMENT, 'Pagamento'),
        (PAID_VIA_COMPENSATION, 'Compensação'),
    ]
    paid_via = models.CharField(
        max_length=12, choices=PAID_VIA_CHOICES, default=PAID_VIA_PAYMENT,
        db_column='pcl_forma_quitacao',
    )
    paid_at = models.DateTimeField(null=True, blank=True, db_column='pcl_pago_em')
    confirmed_at = models.DateTimeField(null=True, blank=True, db_column='pcl_confirmado_em')
    # Último lembrete de pendência enviado — garante idempotência do comando.
    ultimo_lembrete_em = models.DateTimeField(null=True, blank=True, db_column='pcl_ultimo_lembrete_em')

    class Meta:
        db_table = 'parcelas'
        indexes = [
            models.Index(
                fields=['status'],
                name='pcl_status_ativo_idx',
                condition=models.Q(status__in=['pending', 'awaiting_confirmation']),
            ),
        ]

    def __str__(self):
        return f'{self.debtor} deve {self.amount_cents}¢ em {self.debt}'
