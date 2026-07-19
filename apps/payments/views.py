from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.debts.models import Debt, Installment
from apps.groups.models import Group, GroupMember
from apps.users.models import AuditLog, NotificacaoLida
from apps.users.audit import log_event
from apps.users.throttles import PublicPageRateThrottle
from .models import Acerto, ChargeLink, Comprovante
from .serializers import (
    ComprovanteDetailSerializer,
    DeclaracaoPagamentoSerializer,
    PagamentoPublicoSerializer,
)
from .services import (
    confirmar_acerto,
    confirmar_pagamento,
    declarar_pagamento,
    detalhe_acerto,
    gerar_link_cobranca,
    propor_acerto,
    rejeitar_acerto,
    rejeitar_pagamento,
    resumo_acerto,
)


class DashboardView(APIView):
    """
    GET /api/dashboard/ — resumo financeiro do usuário autenticado.

    3 queries: parcelas a receber, parcelas a pagar, grupos ativos.
    Calcula totais e saldo por pessoa em Python.
    """

    def get(self, request):
        user = request.user

        active_group_ids = (
            GroupMember.objects
            .filter(user=user, status=GroupMember.STATUS_ATIVO)
            .values('group_id')
        )

        # Parcelas onde sou credor e a outra parte ainda não pagou
        a_receber_qs = list(
            Installment.objects
            .filter(debt__group_id__in=active_group_ids, debt__paid_by=user)
            .exclude(status=Installment.STATUS_PAID)
            .exclude(debtor=user)
            .select_related('debt__group', 'debtor')
            .order_by('-debt__created_at')
        )

        # Parcelas onde sou devedor e ainda não paguei
        a_pagar_qs = list(
            Installment.objects
            .filter(debt__group_id__in=active_group_ids, debtor=user)
            .exclude(status=Installment.STATUS_PAID)
            .exclude(debt__paid_by=user)
            .select_related('debt__group', 'debt__paid_by')
            .order_by('-debt__created_at')
        )

        # Grupos ativos com contagem de membros ativos
        grupos_qs = (
            Group.objects
            .filter(pk__in=active_group_ids, archived=False)
            .annotate(member_count=Count(
                'members', filter=Q(members__status=GroupMember.STATUS_ATIVO)
            ))
            .only('id', 'name', 'emoji', 'archived')
            .order_by('name')
        )

        # Saldo por pessoa (positivo = me devem, negativo = eu devo)
        balance: dict = {}
        def _name(u):
            return u.get_full_name() or u.username

        for inst in a_receber_qs:
            uid = inst.debtor.pk
            if uid not in balance:
                balance[uid] = {'user': {'id': uid, 'name': _name(inst.debtor)}, 'balance_cents': 0}
            balance[uid]['balance_cents'] += inst.amount_cents

        for inst in a_pagar_qs:
            uid = inst.debt.paid_by.pk
            if uid not in balance:
                balance[uid] = {'user': {'id': uid, 'name': _name(inst.debt.paid_by)}, 'balance_cents': 0}
            balance[uid]['balance_cents'] -= inst.amount_cents

        return Response({
            'total_a_receber': sum(i.amount_cents for i in a_receber_qs),
            'total_a_pagar': sum(i.amount_cents for i in a_pagar_qs),
            'a_receber': [
                {
                    'installment_id': str(i.pk),
                    'debt_id': str(i.debt.pk),
                    'description': i.debt.description,
                    'group_name': i.debt.group.name,
                    'amount_cents': i.amount_cents,
                    'status': i.status,
                    'debtor': {'id': i.debtor.pk, 'name': _name(i.debtor)},
                }
                for i in a_receber_qs
            ],
            'a_pagar': [
                {
                    'installment_id': str(i.pk),
                    'debt_id': str(i.debt.pk),
                    'description': i.debt.description,
                    'group_name': i.debt.group.name,
                    'amount_cents': i.amount_cents,
                    'status': i.status,
                    'creditor': {'id': i.debt.paid_by.pk, 'name': _name(i.debt.paid_by)},
                }
                for i in a_pagar_qs
            ],
            'saldo_por_pessoa': sorted(
                balance.values(), key=lambda x: x['balance_cents'], reverse=True
            ),
            'grupos': [
                {
                    'id': str(g.pk),
                    'name': g.name,
                    'emoji': g.emoji,
                    'archived': g.archived,
                    'member_count': g.member_count,
                }
                for g in grupos_qs
            ],
        })


def _get_parcela(parcela_id, user):
    """Retorna parcela se o user for membro do grupo — 404 caso contrário."""
    try:
        return (
            Installment.objects
            .select_related('debt__paid_by', 'debt__group', 'debtor')
            .get(
                pk=parcela_id,
                debt__group__members__user=user,
                debt__group__members__status='ativo',
            )
        )
    except Installment.DoesNotExist:
        raise NotFound('Parcela não encontrada.')


class ComprovanteCreateView(APIView):
    """POST /api/parcelas/{pk}/comprovante/ — devedor declara pagamento (comprovante opcional)."""

    def post(self, request, pk):
        parcela = _get_parcela(pk, request.user)
        serializer = DeclaracaoPagamentoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            comprovante = declarar_pagamento(
                parcela=parcela,
                file_url=serializer.validated_data.get('file_url') or None,
                enviado_por=request.user,
            )
        except (PermissionError, ValueError) as e:
            raise ValidationError(str(e))

        data = ComprovanteDetailSerializer(comprovante).data if comprovante else {}
        return Response(data, status=status.HTTP_201_CREATED)


class ConfirmarPagamentoView(APIView):
    """PATCH /api/parcelas/{pk}/confirmar/ — credor confirma pagamento."""

    def patch(self, request, pk):
        parcela = _get_parcela(pk, request.user)

        try:
            parcela = confirmar_pagamento(parcela=parcela, confirmado_por=request.user)
        except (PermissionError, ValueError) as e:
            raise ValidationError(str(e))

        return Response({'status': parcela.status, 'confirmed_at': parcela.confirmed_at})


class RejeitarPagamentoView(APIView):
    """POST /api/parcelas/{pk}/rejeitar/ — credor rejeita comprovante."""

    def post(self, request, pk):
        parcela = _get_parcela(pk, request.user)

        try:
            parcela = rejeitar_pagamento(parcela=parcela, rejeitado_por=request.user)
        except (PermissionError, ValueError) as e:
            raise ValidationError(str(e))

        return Response({'status': parcela.status})


class LinkCobrancaCreateView(APIView):
    """POST /api/parcelas/{pk}/link-cobranca/ — credor gera link de cobrança."""

    def post(self, request, pk):
        parcela = _get_parcela(pk, request.user)

        try:
            link = gerar_link_cobranca(parcela=parcela, solicitado_por=request.user)
        except (PermissionError, ValueError) as e:
            raise ValidationError(str(e))

        return Response({'token': str(link.token), 'expires_at': link.expires_at})


class PagamentoPublicoView(generics.RetrieveAPIView):
    """
    GET /api/pagamento/{token}/ — página pública de cobrança, sem autenticação.
    Registra used_at na primeira visita.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PublicPageRateThrottle]
    serializer_class = PagamentoPublicoSerializer
    lookup_field = 'token'

    def get_queryset(self):
        return ChargeLink.objects.select_related(
            'installment__debtor',
            'installment__debt__paid_by',
        )

    def retrieve(self, request, *args, **kwargs):
        link = self.get_object()
        if not link.used_at:
            ChargeLink.objects.filter(pk=link.pk).update(used_at=timezone.now())
        return Response(self.get_serializer(link).data)


class AtividadeListView(APIView):
    """
    GET /api/atividade/ — feed de eventos do usuário autenticado.

    Eventos são derivados do estado atual das despesas e parcelas.
    Inclui flag 'lido' baseada na tabela notificacoes_lidas.
    """

    def get(self, request):
        user = request.user
        eventos = []

        def _name(u):
            return (u.get_full_name() or u.username) if u else None

        # ── Despesas criadas pelo usuário ─────────────────────────────────────
        for d in Debt.objects.filter(created_by=user).select_related('group'):
            eventos.append({
                'id': f'ev-created-{d.id}',
                'tipo': 'debt_created_me',
                'despesa_id': str(d.id),
                'parcela_id': None,
                'data': d.created_at,
                'descricao': d.description,
                'grupo_nome': d.group.name,
                'valor_cents': d.total_amount_cents,
                'contraparte': None,
            })

        # ── Parcelas onde o usuário é devedor ────────────────────────────────
        parcelas_dev = (
            Installment.objects
            .filter(debtor=user)
            .exclude(debt__paid_by=user)  # ignora a parcela-própria do credor (auto-paga)
            .select_related('debt__group', 'debt__paid_by', 'charge_link')
        )
        for p in parcelas_dev:
            base = {
                'despesa_id': str(p.debt_id),
                'parcela_id': str(p.id),
                'descricao': p.debt.description,
                'grupo_nome': p.debt.group.name,
                'valor_cents': p.amount_cents,
                'contraparte': _name(p.debt.paid_by),  # credor
            }
            eventos.append({**base, 'id': f'ev-added-{p.debt_id}', 'tipo': 'debt_added', 'data': p.debt.created_at})
            if p.status == Installment.STATUS_PENDING:
                eventos.append({**base, 'id': f'ev-pending-{p.id}', 'tipo': 'pending_reminder', 'data': p.debt.created_at})
            if p.status == Installment.STATUS_PAID and p.confirmed_at:
                eventos.append({**base, 'id': f'ev-mypaid-{p.id}', 'tipo': 'payment_confirmed', 'data': p.confirmed_at})
            try:
                eventos.append({**base, 'id': f'ev-charged-{p.id}', 'tipo': 'charged', 'data': p.charge_link.created_at})
            except ChargeLink.DoesNotExist:
                pass

        # ── Parcelas onde o usuário é credor ─────────────────────────────────
        parcelas_cred = (
            Installment.objects
            .filter(debt__paid_by=user)
            .exclude(debtor=user)  # ignora a parcela-própria (auto-paga)
            .select_related('debt__group', 'debtor')
            .prefetch_related('comprovantes')
        )
        for p in parcelas_cred:
            base = {
                'despesa_id': str(p.debt_id),
                'parcela_id': str(p.id),
                'descricao': p.debt.description,
                'grupo_nome': p.debt.group.name,
                'valor_cents': p.amount_cents,
                'contraparte': _name(p.debtor),  # devedor
            }
            if p.status == Installment.STATUS_AWAITING:
                cpvs = sorted(p.comprovantes.all(), key=lambda c: c.uploaded_at, reverse=True)
                data_evento = cpvs[0].uploaded_at if cpvs else p.debt.created_at
                eventos.append({**base, 'id': f'ev-proof-{p.id}', 'tipo': 'proof_received', 'data': data_evento})
            if p.status == Installment.STATUS_PAID and p.confirmed_at:
                eventos.append({**base, 'id': f'ev-paid-{p.id}', 'tipo': 'payment_confirmed', 'data': p.confirmed_at})

        # ── Marcar lidos e deduplicar ─────────────────────────────────────────
        lidas = set(
            NotificacaoLida.objects
            .filter(usuario=user)
            .values_list('evento_id', flat=True)
        )
        vistos = set()
        resultado = []
        for e in sorted(eventos, key=lambda x: x['data'], reverse=True):
            if e['id'] not in vistos:
                vistos.add(e['id'])
                e['lido'] = e['id'] in lidas
                resultado.append(e)

        unread_count = sum(1 for e in resultado if not e['lido'])

        # ── Paginação manual ──────────────────────────────────────────────────
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(resultado, request)
        response = paginator.get_paginated_response(page)
        response.data['unread_count'] = unread_count
        return response


class MarcarLidaView(APIView):
    """POST /api/atividade/marcar-lida/ — marca lista de evento_ids como lidos."""

    def post(self, request):
        evento_ids = request.data.get('evento_ids', [])
        if not isinstance(evento_ids, list):
            raise ValidationError({'evento_ids': 'Deve ser uma lista de strings.'})
        if len(evento_ids) > 50:
            raise ValidationError({'evento_ids': 'Máximo de 50 IDs por chamada.'})

        validos = [e for e in evento_ids if isinstance(e, str) and len(e) <= 60]
        NotificacaoLida.objects.bulk_create(
            [NotificacaoLida(usuario=request.user, evento_id=eid) for eid in validos],
            ignore_conflicts=True,
        )
        return Response({'marcados': len(validos)})


class AcertoView(APIView):
    """
    GET  /api/acertar/  — resumo: saldo líquido por pessoa (compensável) + propostas
                          recebidas aguardando sua confirmação.
    POST /api/acertar/  — propõe uma compensação ({para_id}); a outra parte confirma.
    """

    def get(self, request):
        return Response(resumo_acerto(user=request.user))

    def post(self, request):
        para_id = request.data.get('para_id')
        if not para_id:
            raise ValidationError({'para_id': 'Campo obrigatório.'})
        try:
            acerto = propor_acerto(de=request.user, para_id=para_id)
        except ValueError as e:
            raise ValidationError(str(e))
        log_event(
            request, AuditLog.SETTLE_DECLARED, user=request.user,
            detail={'acerto_id': str(acerto.id), 'para_id': str(para_id)},
        )
        return Response({'id': str(acerto.id)}, status=status.HTTP_201_CREATED)


class AcertoDetalheView(APIView):
    """GET /api/acertar/detalhe/?pessoa=<id> — itemiza a compensação com uma pessoa."""

    def get(self, request):
        pessoa = request.query_params.get('pessoa')
        if not pessoa:
            raise ValidationError({'pessoa': 'Campo obrigatório.'})
        try:
            return Response(detalhe_acerto(user=request.user, outro_id=pessoa))
        except ValueError as e:
            raise NotFound(str(e))


def _get_acerto_destinatario(request, pk):
    """Retorna o acerto se o solicitante for o destinatário; 404 caso contrário
    (não vaza a existência da proposta a terceiros)."""
    try:
        return Acerto.objects.get(pk=pk, para=request.user)
    except Acerto.DoesNotExist:
        raise NotFound('Acerto não encontrado.')


class AcertoConfirmarView(APIView):
    """POST /api/acertar/<id>/confirmar/ — quem recebeu confirma (compensa as dívidas)."""

    def post(self, request, pk):
        acerto = _get_acerto_destinatario(request, pk)
        try:
            confirmar_acerto(acerto=acerto, quem=request.user)
        except ValueError as e:
            raise ValidationError(str(e))
        log_event(
            request, AuditLog.SETTLE_CONFIRMED, user=request.user,
            detail={'acerto_id': str(acerto.id), 'de_id': str(acerto.de_id)},
        )
        return Response({'status': 'confirmed'})


class AcertoRejeitarView(APIView):
    """POST /api/acertar/<id>/rejeitar/ — quem recebeu rejeita a proposta."""

    def post(self, request, pk):
        acerto = _get_acerto_destinatario(request, pk)
        try:
            rejeitar_acerto(acerto=acerto, quem=request.user)
        except ValueError as e:
            raise ValidationError(str(e))
        log_event(
            request, AuditLog.SETTLE_DECLARED, user=request.user,
            detail={'acerto_id': str(acerto.id), 'de_id': str(acerto.de_id), 'rejected': True},
        )
        return Response({'status': 'rejected'})
