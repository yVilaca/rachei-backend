from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from debts.models import Installment
from .models import ChargeLink, Comprovante


@transaction.atomic
def enviar_comprovante(*, parcela, file_url, enviado_por):
    """
    Devedor envia comprovante — status muda para awaiting_confirmation.

    Raises PermissionError se o solicitante não for o devedor.
    Raises ValueError se a parcela já estiver paga.
    """
    if enviado_por.pk != parcela.debtor_id:
        raise PermissionError('Apenas o devedor pode enviar o comprovante.')
    if parcela.status == Installment.STATUS_PAID:
        raise ValueError('Parcela já está confirmada como paga.')

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
