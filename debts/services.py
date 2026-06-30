from django.db import transaction

from groups.models import GroupMember
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
    debtor_ids = {p['debtor'].pk for p in parcelas_data}
    member_ids = set(
        GroupMember.objects
        .filter(group=grupo)
        .values_list('user_id', flat=True)
    )
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

    Installment.objects.bulk_create([
        Installment(
            debt=despesa,
            debtor=p['debtor'],
            amount_cents=p['amount_cents'],
        )
        for p in parcelas_data
    ])

    return despesa
