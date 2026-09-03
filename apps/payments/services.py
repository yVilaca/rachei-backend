from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.debts.models import Installment
from apps.groups.models import GroupMember
from apps.notifications import events as notif
from .models import Acerto, ChargeLink, Comprovante


class NegociacaoExistente(Exception):
    """Já existe uma proposta da outra pessoa para você — deve ser revisada, não duplicada."""

    def __init__(self, acerto_id):
        self.acerto_id = acerto_id
        super().__init__('Já existe uma negociação para esta dívida.')


@transaction.atomic
def declarar_pagamento(*, parcela, enviado_por, arquivo=None):
    """
    Devedor declara que pagou — status muda para awaiting_confirmation.
    Comprovante é opcional: se `arquivo` fornecido, registra o upload; caso
    contrário, apenas atualiza o status para revisão do credor.

    Raises PermissionError se o solicitante não for o devedor.
    Raises ValueError se a parcela já estiver paga.
    """
    if enviado_por.pk != parcela.debtor_id:
        raise PermissionError('Apenas o devedor pode declarar o pagamento.')
    if parcela.status == Installment.STATUS_PAID:
        raise ValueError('Parcela já está confirmada como paga.')

    comprovante = None
    if arquivo is not None:
        comprovante = Comprovante.objects.create(
            parcela=parcela,
            arquivo=arquivo,
            uploaded_by=enviado_por,
        )
    Installment.objects.filter(pk=parcela.pk).update(
        status=Installment.STATUS_AWAITING,
        paid_at=timezone.now(),
    )
    credor = parcela.debt.paid_by
    transaction.on_commit(lambda: notif.pagamento_declarado(
        credor=credor, devedor=enviado_por,
        descricao=parcela.debt.description, valor_cents=parcela.amount_cents,
    ))
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
    devedor = parcela.debtor
    transaction.on_commit(lambda: notif.pagamento_confirmado(
        devedor=devedor, credor=confirmado_por,
        descricao=parcela.debt.description, valor_cents=parcela.amount_cents,
    ))
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
    link = ChargeLink.objects.create(
        installment=parcela,
        expires_at=timezone.now() + timedelta(days=7),
    )
    devedor = parcela.debtor
    transaction.on_commit(lambda: notif.cobranca_enviada(
        devedor=devedor, credor=solicitado_por,
        descricao=parcela.debt.description, valor_cents=parcela.amount_cents,
    ))
    return link


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
    devedor = parcela.debtor
    transaction.on_commit(lambda: notif.comprovante_rejeitado(
        devedor=devedor, credor=rejeitado_por,
        descricao=parcela.debt.description, valor_cents=parcela.amount_cents,
    ))
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


def _candidatas(user, outro):
    """Parcelas pendentes entre `user` e `outro` (nos dois sentidos), em grupos ativos."""
    active = _active_group_ids(user)
    return (
        Installment.objects
        .filter(status=Installment.STATUS_PENDING, debt__group_id__in=active)
        .filter(Q(debt__paid_by=user, debtor=outro) | Q(debt__paid_by=outro, debtor=user))
        .select_related('debt', 'debt__group')
        .order_by('debt__created_at')
    )


def _itemizar(installments, user):
    """Separa as parcelas em 'você recebe' (user é credor) e 'você paga' (user é devedor)."""
    recebe, paga = [], []
    for i in installments:
        item = {
            'id': str(i.id),
            'descricao': i.debt.description,
            'grupo': i.debt.group.name,
            'valor_cents': i.amount_cents,
        }
        (recebe if i.debt.paid_by_id == user.pk else paga).append(item)
    return recebe, paga


def _tem_mutua_itens(installments, user):
    """Há, por grupo, parcelas nos dois sentidos entre `user` e a contraparte?"""
    porg = {}
    for i in installments:
        r_p = porg.setdefault(i.debt.group_id, [0, 0])
        r_p[0 if i.debt.paid_by_id == user.pk else 1] += i.amount_cents
    return any(a > 0 and b > 0 for a, b in porg.values())


def _resolver_pessoa(pk):
    User = get_user_model()
    u = User.objects.filter(pk=pk).first()
    if u is None:
        raise ValueError('Pessoa não encontrada.')
    return u


def detalhe_acerto(*, user, outro_id=None, acerto=None):
    """
    Itemiza uma compensação (parcelas dos dois sentidos + totais/saldo), da
    perspectiva de `user`. Por `outro_id`: todas as parcelas candidatas com a
    pessoa (usado ao propor). Por `acerto`: só as parcelas selecionadas na
    proposta (usado ao revisar/confirmar).
    """
    if acerto is not None:
        outro = acerto.de if user.pk == acerto.para_id else acerto.para
        installments = list(
            acerto.parcelas
            .filter(status=Installment.STATUS_PENDING)
            .select_related('debt', 'debt__group')
            .order_by('debt__created_at')
        )
    else:
        outro = _resolver_pessoa(outro_id)
        installments = list(_candidatas(user, outro))

    voce_recebe, voce_paga = _itemizar(installments, user)
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


@transaction.atomic
def propor_acerto(*, de, para_id, parcela_ids=None):
    """
    Cria (ou reutiliza) uma proposta de compensação pendente de `de` para `para_id`,
    com as parcelas a abater. `parcela_ids=None` seleciona todas as candidatas.
    """
    if str(de.pk) == str(para_id):
        raise ValueError('Não é possível acertar consigo mesmo.')
    para = _resolver_pessoa(para_id)

    candidatas = _candidatas(de, para)
    if parcela_ids is not None:
        ids = {str(i) for i in parcela_ids}
        selecionadas = [i for i in candidatas if str(i.id) in ids]
        if len(selecionadas) != len(ids):
            raise ValueError('Seleção inválida de parcelas.')
    else:
        selecionadas = list(candidatas)

    if not _tem_mutua_itens(selecionadas, de):
        raise ValueError('Selecione dívidas nos dois sentidos para compensar.')

    # Já existe proposta da outra pessoa para você? Não crie uma concorrente —
    # sinaliza para o app te levar a revisar (aceitar/recusar) a existente.
    reversa = Acerto.objects.filter(
        de_id=para_id, para=de, status=Acerto.STATUS_PENDING,
    ).first()
    if reversa is not None:
        raise NegociacaoExistente(reversa.id)

    existente = Acerto.objects.filter(
        de=de, para_id=para_id, status=Acerto.STATUS_PENDING,
    ).first()
    acerto = existente or Acerto.objects.create(de=de, para_id=para_id)
    acerto.parcelas.set(selecionadas)  # substitui a seleção
    if existente is None:  # notifica só na proposta nova, não ao reajustar a seleção
        transaction.on_commit(lambda: notif.compensacao_proposta(destinatario=para, proponente=de))
    return acerto


@transaction.atomic
def confirmar_acerto(*, acerto, quem):
    """
    A outra parte confirma. Compensa, por grupo, as parcelas selecionadas ainda
    pendentes: abate o valor comum dos dois sentidos marcando essas parcelas como
    pagas por compensação (dividindo a parcela de fronteira quando necessário). O
    resíduo permanece pendente na própria dívida — não cria dívida nova.
    """
    if quem.pk != acerto.para_id:
        raise PermissionError('Apenas quem recebeu a proposta pode confirmar.')
    if acerto.status != Acerto.STATUS_PENDING:
        raise ValueError('Este acerto já foi resolvido.')

    de, para = acerto.de, acerto.para
    now = timezone.now()

    # Trava e relê as parcelas selecionadas ainda pendentes. Serializa confirmações
    # concorrentes: uma proposta cruzada confirmada ao mesmo tempo espera esta trava
    # e, ao seguir, encontra as parcelas já quitadas (vira no-op), evitando abater
    # em duplicidade.
    sel_ids = list(acerto.parcelas.values_list('pk', flat=True))
    parcelas = list(
        Installment.objects.select_for_update(of=('self',))
        .filter(pk__in=sel_ids, status=Installment.STATUS_PENDING)
        .select_related('debt')
    )

    # Agrupa por grupo e sentido (do ponto de vista de `de`).
    porg = {}  # group_id -> {'recebo': [inst], 'devo': [inst]}
    for i in parcelas:
        b = porg.setdefault(i.debt.group_id, {'recebo': [], 'devo': []})
        b['recebo' if i.debt.paid_by_id == de.pk else 'devo'].append(i)

    for b in porg.values():
        recebo = sum(i.amount_cents for i in b['recebo'])
        devo = sum(i.amount_cents for i in b['devo'])
        if recebo <= 0 or devo <= 0:
            continue  # sem mutualidade na seleção deste grupo — não compensa

        compensado = min(recebo, devo)  # valor abatido em cada sentido
        _abater(b['recebo'], compensado, acerto, now)
        _abater(b['devo'], compensado, acerto, now)

    acerto.status = Acerto.STATUS_CONFIRMED
    acerto.resolved_at = now
    acerto.save(update_fields=['status', 'resolved_at'])

    # A compensação que qualquer outra proposta pendente entre os dois pedia acabou
    # de acontecer — resolve-as (ex.: a proposta cruzada de `para` para `de`) para
    # não ficarem penduradas aguardando uma confirmação que já não faz nada.
    Acerto.objects.filter(status=Acerto.STATUS_PENDING).filter(
        Q(de=de, para=para) | Q(de=para, para=de)
    ).exclude(pk=acerto.pk).update(status=Acerto.STATUS_CONFIRMED, resolved_at=now)

    transaction.on_commit(lambda: notif.compensacao_confirmada(proponente=de, confirmador=para))
    return acerto


def _abater(parcelas, alvo, acerto, now):
    """
    Marca parcelas como pagas por compensação até somar `alvo`, ligando-as ao
    `acerto` (auditoria). Se a parcela de fronteira ultrapassa o alvo, ela é
    dividida: a parte abatida vira uma parcela paga e o restante segue pendente
    na parcela original (mesma dívida) — nunca cria dívida nova.
    """
    restante = alvo
    for inst in parcelas:
        if restante <= 0:
            break
        if inst.amount_cents <= restante:
            restante -= inst.amount_cents
            Installment.objects.filter(pk=inst.pk).update(
                status=Installment.STATUS_PAID, paid_at=now, confirmed_at=now,
                paid_via=Installment.PAID_VIA_COMPENSATION,
            )
            acerto.parcelas_quitadas.add(inst)
        else:
            # Divide: original mantém o resto pendente; parte abatida vira paga.
            resto = inst.amount_cents - restante
            Installment.objects.filter(pk=inst.pk).update(amount_cents=resto)
            paga = Installment.objects.create(
                debt=inst.debt, debtor=inst.debtor, amount_cents=restante,
                status=Installment.STATUS_PAID, paid_at=now, confirmed_at=now,
                paid_via=Installment.PAID_VIA_COMPENSATION,
            )
            acerto.parcelas_quitadas.add(paga)
            restante = 0


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
