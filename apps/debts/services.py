from django.db import transaction
from django.utils import timezone

from apps.groups.models import GroupMember
from .models import Debt, Installment


@transaction.atomic
def criar_despesa(*, grupo, paid_by, created_by, description, total_amount_cents, split_type, parcelas_data):
    """
    Cria uma Despesa com suas Parcelas atomicamente.

    parcelas_data: list of {'debtor': User, 'amount_cents': int}

    Para split_type='equal', distribui o valor igualmente e reparte os centavos
    restantes entre os primeiros devedores (distribuição justa).

    Raises ValueError se algum devedor não for membro do grupo.
    """
    member_ids = set(
        GroupMember.objects
        .filter(group=grupo, status=GroupMember.STATUS_ATIVO)
        .values_list('user_id', flat=True)
    )
    if paid_by.pk not in member_ids:
        raise PermissionError('Você não é membro deste grupo.')

    debtor_ids = {p['debtor'].pk for p in parcelas_data}
    invalidos = debtor_ids - member_ids
    if invalidos:
        raise ValueError('Um ou mais devedores não são membros do grupo.')

    if split_type == Debt.SPLIT_EQUAL:
        n = len(parcelas_data)
        base = total_amount_cents // n
        remainder = total_amount_cents % n
        for i, p in enumerate(parcelas_data):
            p['amount_cents'] = base + (1 if i < remainder else 0)

    despesa = Debt.objects.create(
        group=grupo,
        paid_by=paid_by,
        created_by=created_by,
        description=description,
        total_amount_cents=total_amount_cents,
        split_type=split_type,
    )

    now = timezone.now()
    Installment.objects.bulk_create([
        Installment(
            debt=despesa,
            debtor=p['debtor'],
            amount_cents=p['amount_cents'],
            status=Installment.STATUS_PAID if p['debtor'].pk == paid_by.pk else Installment.STATUS_PENDING,
            paid_at=now if p['debtor'].pk == paid_by.pk else None,
            confirmed_at=now if p['debtor'].pk == paid_by.pk else None,
        )
        for p in parcelas_data
    ])

    return despesa
