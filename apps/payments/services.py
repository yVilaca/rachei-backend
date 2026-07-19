from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.debts.models import Debt, Installment
from apps.groups.models import GroupMember
from .models import Acerto, ChargeLink, Comprovante


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


# ── Acertar contas (compensação / netting entre duas pessoas) ────────────────

def _active_group_ids(user):
    return set(
        GroupMember.objects
        .filter(user=user, status=GroupMember.STATUS_ATIVO)
        .values_list('group_id', flat=True)
    )


def _pares_pendentes(user):
    """
    Constrói, por contraparte, os totais pendentes por grupo nos dois sentidos.
    Retorna: { outro_id: { grupo_id: [recebo_dele, devo_a_ele] } } (em centavos).
    """
    active = _active_group_ids(user)
    pares = {}

    recv = (
        Installment.objects
        .filter(debt__paid_by=user, status=Installment.STATUS_PENDING, debt__group_id__in=active)
        .exclude(debtor=user)
        .values('debtor', 'debt__group_id')
        .annotate(total=Sum('amount_cents'))
    )
    for r in recv:
        pares.setdefault(r['debtor'], {}).setdefault(r['debt__group_id'], [0, 0])[0] += r['total']

    pay = (
        Installment.objects
        .filter(debtor=user, status=Installment.STATUS_PENDING, debt__group_id__in=active)
        .exclude(debt__paid_by=user)
        .values('debt__paid_by', 'debt__group_id')
        .annotate(total=Sum('amount_cents'))
    )
    for p in pay:
        pares.setdefault(p['debt__paid_by'], {}).setdefault(p['debt__group_id'], [0, 0])[1] += p['total']

    return pares


def resumo_acerto(*, user):
    """
    Por contraparte: saldo líquido (positivo = te devem; negativo = você deve) e
    se é compensável (há dívida mútua em algum grupo). Mais os acertos que
    aguardam a confirmação do `user`.
    """
    User = get_user_model()
    pares = _pares_pendentes(user)

    enviados = set(
        Acerto.objects.filter(de=user, status=Acerto.STATUS_PENDING).values_list('para_id', flat=True)
    )
    recebidos = list(Acerto.objects.filter(para=user, status=Acerto.STATUS_PENDING))

    ids = set(pares) | {a.de_id for a in recebidos}
    nomes = {u.pk: (u.get_full_name() or u.username) for u in User.objects.filter(pk__in=ids)}

    pessoas = []
    for cp_id, grupos in pares.items():
        saldo = sum(a - b for a, b in grupos.values())
        compensavel = any(a > 0 and b > 0 for a, b in grupos.values())
        if saldo == 0 and not compensavel:
            continue
        pessoas.append({
            'pessoa': {'id': cp_id, 'name': nomes.get(cp_id)},
            'saldo_cents': saldo,
            'compensavel': compensavel,
            'acerto_enviado': cp_id in enviados,
        })
    pessoas.sort(key=lambda p: p['saldo_cents'])  # quem você mais deve primeiro

    def _saldo_com(outro_id):
        grupos = pares.get(outro_id, {})
        return sum(a - b for a, b in grupos.values())

    a_confirmar = [
        {'id': str(a.id), 'de': {'id': a.de_id, 'name': nomes.get(a.de_id)},
         'saldo_cents': _saldo_com(a.de_id)}
        for a in recebidos
    ]

    return {'pessoas': pessoas, 'a_confirmar': a_confirmar}


def detalhe_acerto(*, user, outro_id):
    """
    Itemiza a compensação entre `user` e `outro_id`: as parcelas pendentes nos
    dois sentidos (com descrição e grupo) e os totais/saldo líquido.
    """
    User = get_user_model()
    outro = User.objects.filter(pk=outro_id).first()
    if outro is None:
        raise ValueError('Pessoa não encontrada.')

    active = _active_group_ids(user)

    def _itens(credor, devedor):
        qs = (
            Installment.objects
            .filter(
                debt__paid_by=credor, debtor=devedor,
                status=Installment.STATUS_PENDING, debt__group_id__in=active,
            )
            .select_related('debt', 'debt__group')
            .order_by('debt__created_at')
        )
        return [
            {
                'id': str(i.id),
                'descricao': i.debt.description,
                'grupo': i.debt.group.name,
                'valor_cents': i.amount_cents,
            }
            for i in qs
        ]

    voce_recebe = _itens(credor=user, devedor=outro)   # o que `outro` deve a você
    voce_paga = _itens(credor=outro, devedor=user)      # o que você deve a `outro`
    total_recebe = sum(i['valor_cents'] for i in voce_recebe)
    total_paga = sum(i['valor_cents'] for i in voce_paga)

    return {
        'pessoa': {'id': outro.pk, 'name': outro.get_full_name() or outro.username},
        'voce_recebe': voce_recebe,
        'voce_paga': voce_paga,
        'total_recebe': total_recebe,
        'total_paga': total_paga,
        'saldo_cents': total_recebe - total_paga,
        'compensavel': total_recebe > 0 and total_paga > 0,
    }


def _tem_mutua(de, para_id):
    """Há dívida mútua (nos dois sentidos) entre `de` e `para_id` em algum grupo?"""
    grupos = _pares_pendentes(de).get(para_id, {})
    return any(a > 0 and b > 0 for a, b in grupos.values())


@transaction.atomic
def propor_acerto(*, de, para_id):
    """Cria (ou reutiliza) uma proposta de compensação pendente de `de` para `para_id`."""
    if str(de.pk) == str(para_id):
        raise ValueError('Não é possível acertar consigo mesmo.')
    if not _tem_mutua(de, para_id):
        raise ValueError('Não há dívidas mútuas para compensar com esta pessoa.')

    existente = Acerto.objects.filter(
        de=de, para_id=para_id, status=Acerto.STATUS_PENDING,
    ).first()
    if existente:
        return existente
    return Acerto.objects.create(de=de, para_id=para_id)


@transaction.atomic
def confirmar_acerto(*, acerto, quem):
    """
    A outra parte confirma. Compensa as dívidas mútuas por grupo: quita as
    parcelas dos dois sentidos e cria uma única dívida líquida com o saldo.
    """
    if quem.pk != acerto.para_id:
        raise PermissionError('Apenas quem recebeu a proposta pode confirmar.')
    if acerto.status != Acerto.STATUS_PENDING:
        raise ValueError('Este acerto já foi resolvido.')

    de, para = acerto.de, acerto.para
    pares = _pares_pendentes(de)  # da perspectiva de `de`: [recebo_de_para, devo_a_para]
    grupos = pares.get(para.pk, {})
    now = timezone.now()

    for grupo_id, (recebo, devo) in grupos.items():
        if recebo <= 0 or devo <= 0:
            continue  # sem mutualidade neste grupo — não compensa

        # Quita (por compensação) as parcelas pendentes dos dois sentidos no grupo
        Installment.objects.filter(
            debt__group_id=grupo_id, status=Installment.STATUS_PENDING,
            debt__paid_by=de, debtor=para,
        ).update(status=Installment.STATUS_PAID, paid_at=now, confirmed_at=now)
        Installment.objects.filter(
            debt__group_id=grupo_id, status=Installment.STATUS_PENDING,
            debt__paid_by=para, debtor=de,
        ).update(status=Installment.STATUS_PAID, paid_at=now, confirmed_at=now)

        liquido = recebo - devo  # >0: para deve a de; <0: de deve a para
        if liquido != 0:
            credor, devedor = (de, para) if liquido > 0 else (para, de)
            _criar_divida_liquida(grupo_id, credor, devedor, abs(liquido), criado_por=de)

    acerto.status = Acerto.STATUS_CONFIRMED
    acerto.resolved_at = now
    acerto.save(update_fields=['status', 'resolved_at'])
    return acerto


def _criar_divida_liquida(grupo_id, credor, devedor, valor_cents, criado_por):
    """Cria a dívida consolidada do saldo remanescente após a compensação."""
    divida = Debt.objects.create(
        group_id=grupo_id, paid_by=credor, created_by=criado_por,
        description='Acerto de contas', total_amount_cents=valor_cents,
        split_type=Debt.SPLIT_CUSTOM,
    )
    Installment.objects.create(
        debt=divida, debtor=devedor, amount_cents=valor_cents,
        status=Installment.STATUS_PENDING,
    )


@transaction.atomic
def rejeitar_acerto(*, acerto, quem):
    if quem.pk != acerto.para_id:
        raise PermissionError('Apenas quem recebeu a proposta pode rejeitar.')
    if acerto.status != Acerto.STATUS_PENDING:
        raise ValueError('Este acerto já foi resolvido.')
    acerto.status = Acerto.STATUS_REJECTED
    acerto.resolved_at = timezone.now()
    acerto.save(update_fields=['status', 'resolved_at'])
    return acerto
