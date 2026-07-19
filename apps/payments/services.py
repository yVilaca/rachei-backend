from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.debts.models import Installment
from apps.groups.models import GroupMember
from .models import ChargeLink, Comprovante


@transaction.atomic
def declarar_pagamento(*, parcela, enviado_por, file_url=None):
    """
    Devedor declara que pagou — status muda para awaiting_confirmation.
    Comprovante é opcional: se file_url fornecido, registra; caso contrário,
    apenas atualiza o status para revisão do credor.

    Raises PermissionError se o solicitante não for o devedor.
    Raises ValueError se a parcela já estiver paga.
    """
    if enviado_por.pk != parcela.debtor_id:
        raise PermissionError('Apenas o devedor pode declarar o pagamento.')
    if parcela.status == Installment.STATUS_PAID:
        raise ValueError('Parcela já está confirmada como paga.')

    comprovante = None
    if file_url:
        comprovante = Comprovante.objects.create(
            parcela=parcela,
            file_url=file_url,
            uploaded_by=enviado_por,
        )
    Installment.objects.filter(pk=parcela.pk).update(
        status=Installment.STATUS_AWAITING,
        paid_at=timezone.now(),
    )
    return comprovante


@transaction.atomic
def confirmar_pagamento(*, parcela, confirmado_por):
    """
    Credor confirma pagamento — status muda para paid.

    Raises PermissionError se o solicitante não for o credor.
    Raises ValueError se a parcela não estiver aguardando confirmação.
    """
    if confirmado_por.pk != parcela.debt.paid_by_id:
        raise PermissionError('Apenas o credor pode confirmar o pagamento.')
    if parcela.status != Installment.STATUS_AWAITING:
        raise ValueError('Parcela não está aguardando confirmação.')

    Installment.objects.filter(pk=parcela.pk).update(
        status=Installment.STATUS_PAID,
        confirmed_at=timezone.now(),
    )
    parcela.refresh_from_db(fields=['status', 'confirmed_at'])
    return parcela


@transaction.atomic
def gerar_link_cobranca(*, parcela, solicitado_por):
    """
    Credor gera ou renova o link de cobrança para uma parcela.

    Raises PermissionError se o solicitante não for o credor.
    Raises ValueError se a parcela já estiver paga.
    """
    if solicitado_por.pk != parcela.debt.paid_by_id:
        raise PermissionError('Apenas o credor pode gerar o link de cobrança.')
    if parcela.status == Installment.STATUS_PAID:
        raise ValueError('Parcela já está paga.')

    ChargeLink.objects.filter(installment=parcela).delete()
    return ChargeLink.objects.create(
        installment=parcela,
        expires_at=timezone.now() + timedelta(days=7),
    )


@transaction.atomic
def rejeitar_pagamento(*, parcela, rejeitado_por):
    """
    Credor rejeita o comprovante — status volta para pending.

    Raises PermissionError se o solicitante não for o credor.
    Raises ValueError se a parcela não estiver aguardando confirmação.
    """
    if rejeitado_por.pk != parcela.debt.paid_by_id:
        raise PermissionError('Apenas o credor pode rejeitar o comprovante.')
    if parcela.status != Installment.STATUS_AWAITING:
        raise ValueError('Parcela não está aguardando confirmação.')

    Installment.objects.filter(pk=parcela.pk).update(
        status=Installment.STATUS_PENDING,
        paid_at=None,
    )
    parcela.refresh_from_db(fields=['status', 'paid_at'])
    return parcela


# ── Acertar contas (settle up par a par, em lote) ────────────────────────────

def _minhas_dividas_qs(devedor):
    """Parcelas pendentes onde `devedor` deve a outro membro (grupo ativo)."""
    return (
        Installment.objects
        .filter(debtor=devedor, status=Installment.STATUS_PENDING)
        .exclude(debt__paid_by=devedor)
        .filter(
            debt__group__members__user=devedor,
            debt__group__members__status=GroupMember.STATUS_ATIVO,
        )
    )


def resumo_acerto(*, user):
    """
    O que o `user` deve (agrupado por credor) e os acertos declarados a ele
    aguardando sua confirmação (agrupado por devedor). Valores em centavos.
    """
    User = get_user_model()

    deve = list(
        _minhas_dividas_qs(user)
        .values('debt__paid_by')
        .annotate(total=Sum('amount_cents'))
    )
    a_confirmar = list(
        Installment.objects
        .filter(debt__paid_by=user, status=Installment.STATUS_AWAITING)
        .values('debtor')
        .annotate(total=Sum('amount_cents'))
    )

    ids = {d['debt__paid_by'] for d in deve} | {c['debtor'] for c in a_confirmar}
    nomes = {u.pk: (u.get_full_name() or u.username) for u in User.objects.filter(pk__in=ids)}

    return {
        'voce_deve': [
            {'pessoa': {'id': d['debt__paid_by'], 'name': nomes.get(d['debt__paid_by'])},
             'valor_cents': d['total']}
            for d in sorted(deve, key=lambda x: -x['total'])
        ],
        'a_confirmar': [
            {'pessoa': {'id': c['debtor'], 'name': nomes.get(c['debtor'])},
             'valor_cents': c['total']}
            for c in sorted(a_confirmar, key=lambda x: -x['total'])
        ],
    }


@transaction.atomic
def declarar_acerto(*, devedor, para_id=None, grupo_id=None):
    """
    Declara pagas (awaiting_confirmation) as parcelas pendentes do `devedor`.
    Sem `para_id` = com todos que ele deve; com `para_id` = só com aquela pessoa.
    `grupo_id` limita a um grupo. Só mexe nas parcelas do próprio devedor.
    """
    qs = _minhas_dividas_qs(devedor)
    if para_id:
        qs = qs.filter(debt__paid_by_id=para_id)
    if grupo_id:
        qs = qs.filter(debt__group_id=grupo_id)

    ids = list(qs.values_list('id', flat=True))
    if not ids:
        raise ValueError('Nada a acertar.')

    Installment.objects.filter(id__in=ids).update(
        status=Installment.STATUS_AWAITING, paid_at=timezone.now(),
    )
    return len(ids)


@transaction.atomic
def confirmar_acerto(*, credor, de_id, grupo_id=None):
    """
    Credor confirma o acerto declarado por `de_id`: marca como pagas todas as
    parcelas aguardando confirmação em que ele é o credor e `de_id` o devedor.
    """
    qs = Installment.objects.filter(
        debt__paid_by=credor, debtor_id=de_id, status=Installment.STATUS_AWAITING,
    )
    if grupo_id:
        qs = qs.filter(debt__group_id=grupo_id)

    ids = list(qs.values_list('id', flat=True))
    if not ids:
        raise ValueError('Nenhum acerto aguardando sua confirmação desta pessoa.')

    Installment.objects.filter(id__in=ids).update(
        status=Installment.STATUS_PAID, confirmed_at=timezone.now(),
    )
    return len(ids)
