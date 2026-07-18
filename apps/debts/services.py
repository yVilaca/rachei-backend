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

    _criar_parcelas(despesa, paid_by.pk, parcelas_data)
    return despesa


def _criar_parcelas(despesa, paid_by_id, parcelas_data):
    """Cria as parcelas; a do próprio credor já nasce paga (auto-quitada)."""
    now = timezone.now()
    Installment.objects.bulk_create([
        Installment(
            debt=despesa,
            debtor=p['debtor'],
            amount_cents=p['amount_cents'],
            status=Installment.STATUS_PAID if p['debtor'].pk == paid_by_id else Installment.STATUS_PENDING,
            paid_at=now if p['debtor'].pk == paid_by_id else None,
            confirmed_at=now if p['debtor'].pk == paid_by_id else None,
        )
        for p in parcelas_data
    ])


def _alteravel(despesa) -> bool:
    """
    True se a dívida ainda pode ter valores alterados/ser excluída — ou seja,
    nenhum devedor (exceto o próprio credor, auto-quitado) saiu de 'pendente'.
    Protege dinheiro já em acerto de ser apagado.
    """
    return not (
        despesa.installments
        .exclude(debtor_id=despesa.paid_by_id)
        .exclude(status=Installment.STATUS_PENDING)
        .exists()
    )


@transaction.atomic
def editar_despesa(*, despesa, editor, description, total_amount_cents=None,
                   split_type=None, parcelas_data=None):
    """
    Edita a dívida. A descrição é sempre editável.
    Valores/divisão/parcelas só quando `parcelas_data` é enviado E a dívida ainda
    é alterável (ninguém pagou). Recria as parcelas atomicamente.

    Raises PermissionError se não for o credor; ValueError em regra de negócio.
    """
    if editor.pk != despesa.paid_by_id:
        raise PermissionError('Apenas quem registrou pode editar a dívida.')

    despesa.description = description

    if parcelas_data is not None:
        if not _alteravel(despesa):
            raise ValueError('Já há pagamento em andamento; só a descrição pode ser alterada.')

        member_ids = set(
            GroupMember.objects
            .filter(group=despesa.group, status=GroupMember.STATUS_ATIVO)
            .values_list('user_id', flat=True)
        )
        debtor_ids = {p['debtor'].pk for p in parcelas_data}
        if debtor_ids - member_ids:
            raise ValueError('Um ou mais devedores não são membros do grupo.')

        if split_type == Debt.SPLIT_EQUAL:
            n = len(parcelas_data)
            base = total_amount_cents // n
            remainder = total_amount_cents % n
            for i, p in enumerate(parcelas_data):
                p['amount_cents'] = base + (1 if i < remainder else 0)

        despesa.total_amount_cents = total_amount_cents
        despesa.split_type = split_type
        despesa.installments.all().delete()
        _criar_parcelas(despesa, despesa.paid_by_id, parcelas_data)

    despesa.save()
    return despesa


@transaction.atomic
def excluir_despesa(*, despesa, ator):
    """
    Exclui a dívida. Só o credor, e só se ninguém pagou (protege acerto em andamento).

    Raises PermissionError se não for o credor; ValueError se já houver pagamento.
    """
    if ator.pk != despesa.paid_by_id:
        raise PermissionError('Apenas quem registrou pode excluir a dívida.')
    if not _alteravel(despesa):
        raise ValueError('Não é possível excluir: já há pagamento em andamento nesta dívida.')
    despesa.delete()
