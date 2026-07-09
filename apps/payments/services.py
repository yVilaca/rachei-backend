from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.debts.models import Installment
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
