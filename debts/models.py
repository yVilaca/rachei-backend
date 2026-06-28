import uuid
from django.conf import settings
from django.db import models


class Debt(models.Model):
    SPLIT_EQUAL = 'equal'
    SPLIT_CUSTOM = 'custom'
    SPLIT_CHOICES = [(SPLIT_EQUAL, 'Equal'), (SPLIT_CUSTOM, 'Custom')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        'groups.Group', on_delete=models.CASCADE, related_name='debts'
    )
    description = models.CharField(max_length=255)
    total_amount_cents = models.PositiveIntegerField()
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='debts_paid',
    )
    split_type = models.CharField(max_length=10, choices=SPLIT_CHOICES, default=SPLIT_EQUAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'debts'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.description} ({self.group})'


class Installment(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_AWAITING = 'awaiting_confirmation'
    STATUS_PAID = 'paid'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_AWAITING, 'Awaiting confirmation'),
        (STATUS_PAID, 'Paid'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    debt = models.ForeignKey(Debt, on_delete=models.CASCADE, related_name='installments')
    debtor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='installments_owed',
    )
    amount_cents = models.PositiveIntegerField()
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default=STATUS_PENDING)
    proof_url = models.URLField(blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'installments'

    def __str__(self):
        return f'{self.debtor} owes {self.amount_cents}¢ on {self.debt}'
