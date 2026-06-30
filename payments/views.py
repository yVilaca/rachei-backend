from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from debts.models import Debt, Installment
from users.models import NotificacaoLida
from .models import ChargeLink, Comprovante
from .serializers import (
    ComprovanteDetailSerializer,
    ComprovanteFormSerializer,
    PagamentoPublicoSerializer,
)
from .services import confirmar_pagamento, enviar_comprovante, gerar_link_cobranca


def _get_parcela(parcela_id, user):
    """Retorna parcela se o user for membro do grupo — 404 caso contrário."""
    try:
        return (
            Installment.objects
            .select_related('debt__paid_by', 'debt__group', 'debtor')
            .get(pk=parcela_id, debt__group__members__user=user)
        )
    except Installment.DoesNotExist:
        raise NotFound('Parcela não encontrada.')


class ComprovanteCreateView(APIView):
    """POST /api/parcelas/{pk}/comprovante/ — devedor envia comprovante."""

    def post(self, request, pk):
        parcela = _get_parcela(pk, request.user)
        serializer = ComprovanteFormSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            comprovante = enviar_comprovante(
                parcela=parcela,
                file_url=serializer.validated_data['file_url'],
                enviado_por=request.user,
            )
        except (PermissionError, ValueError) as e:
            raise ValidationError(str(e))

        return Response(ComprovanteDetailSerializer(comprovante).data, status=status.HTTP_201_CREATED)


class ConfirmarPagamentoView(APIView):
    """PATCH /api/parcelas/{pk}/confirmar/ — credor confirma pagamento."""

    def patch(self, request, pk):
        parcela = _get_parcela(pk, request.user)

        try:
            parcela = confirmar_pagamento(parcela=parcela, confirmado_por=request.user)
        except (PermissionError, ValueError) as e:
            raise ValidationError(str(e))

        return Response({'status': parcela.status, 'confirmed_at': parcela.confirmed_at})


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

        # ── Despesas criadas pelo usuário ─────────────────────────────────────
        for d in Debt.objects.filter(created_by=user).only('id', 'created_at'):
            eventos.append({
                'id': f'ev-created-{d.id}',
                'tipo': 'debt_created_me',
                'despesa_id': str(d.id),
                'parcela_id': None,
                'data': d.created_at,
            })

        # ── Parcelas onde o usuário é devedor ────────────────────────────────
        parcelas_dev = list(
            Installment.objects
            .filter(debtor=user)
            .select_related('debt', 'charge_link')
            .only('id', 'status', 'paid_at', 'confirmed_at', 'debt_id',
                  'debt__created_at', 'debt__id')
        )
        for p in parcelas_dev:
            eventos.append({
                'id': f'ev-added-{p.debt_id}',
                'tipo': 'debt_added',
                'despesa_id': str(p.debt_id),
                'parcela_id': str(p.id),
                'data': p.debt.created_at,
            })
            if p.status == Installment.STATUS_PENDING:
                eventos.append({
                    'id': f'ev-pending-{p.id}',
                    'tipo': 'pending_reminder',
                    'despesa_id': str(p.debt_id),
                    'parcela_id': str(p.id),
                    'data': p.debt.created_at,
                })
            if p.status == Installment.STATUS_PAID and p.confirmed_at:
                eventos.append({
                    'id': f'ev-mypaid-{p.id}',
                    'tipo': 'payment_confirmed',
                    'despesa_id': str(p.debt_id),
                    'parcela_id': str(p.id),
                    'data': p.confirmed_at,
                })
            try:
                eventos.append({
                    'id': f'ev-charged-{p.id}',
                    'tipo': 'charged',
                    'despesa_id': str(p.debt_id),
                    'parcela_id': str(p.id),
                    'data': p.charge_link.created_at,
                })
            except ChargeLink.DoesNotExist:
                pass

        # ── Parcelas onde o usuário é credor ─────────────────────────────────
        parcelas_cred = list(
            Installment.objects
            .filter(debt__paid_by=user)
            .select_related('debt')
            .prefetch_related('comprovantes')
            .only('id', 'status', 'confirmed_at', 'debt_id', 'debt__created_at')
        )
        for p in parcelas_cred:
            if p.status == Installment.STATUS_AWAITING:
                cpvs = sorted(p.comprovantes.all(), key=lambda c: c.uploaded_at, reverse=True)
                data_evento = cpvs[0].uploaded_at if cpvs else p.debt.created_at
                eventos.append({
                    'id': f'ev-proof-{p.id}',
                    'tipo': 'proof_received',
                    'despesa_id': str(p.debt_id),
                    'parcela_id': str(p.id),
                    'data': data_evento,
                })
            if p.status == Installment.STATUS_PAID and p.confirmed_at:
                eventos.append({
                    'id': f'ev-paid-{p.id}',
                    'tipo': 'payment_confirmed',
                    'despesa_id': str(p.debt_id),
                    'parcela_id': str(p.id),
                    'data': p.confirmed_at,
                })

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

        # ── Paginação manual ──────────────────────────────────────────────────
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(resultado, request)
        return paginator.get_paginated_response(page)


class MarcarLidaView(APIView):
    """POST /api/atividade/marcar-lida/ — marca lista de evento_ids como lidos."""

    def post(self, request):
        evento_ids = request.data.get('evento_ids', [])
        if not isinstance(evento_ids, list):
            raise ValidationError({'evento_ids': 'Deve ser uma lista de strings.'})

        validos = [e for e in evento_ids if isinstance(e, str) and len(e) <= 60]
        NotificacaoLida.objects.bulk_create(
            [NotificacaoLida(usuario=request.user, evento_id=eid) for eid in validos],
            ignore_conflicts=True,
        )
        return Response({'marcados': len(validos)})
