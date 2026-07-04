from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.groups.models import Group, GroupMember
from apps.groups.permissions import IsGroupMember
from .models import Debt, Installment

_grupos_do_user = lambda user: GroupMember.objects.filter(user=user).values('group_id')
from .serializers import (
    DespesaDetailSerializer,
    DespesaFormSerializer,
    DespesaListSerializer,
    ParcelaDetailSerializer,
)
from .services import criar_despesa


def _verificar_membro(grupo_id, user):
    if not GroupMember.objects.filter(group_id=grupo_id, user=user).exists():
        raise PermissionDenied('Você não é membro deste grupo.')


class DespesasPorGrupoView(generics.ListAPIView):
    """GET /api/grupos/{grupo_pk}/despesas/ — despesas de um grupo."""
    serializer_class = DespesaListSerializer

    def get_queryset(self):
        _verificar_membro(self.kwargs['grupo_pk'], self.request.user)
        return (
            Debt.objects
            .filter(group_id=self.kwargs['grupo_pk'])
            .select_related('paid_by')
            .order_by('-created_at')
        )


class DespesaCreateView(APIView):
    """POST /api/despesas/ — cria despesa com parcelas atomicamente."""

    permission_classes = [permissions.IsAuthenticated, IsGroupMember]

    def post(self, request):
        serializer = DespesaFormSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        grupo = get_object_or_404(Group, pk=data['grupo_id'])
        # has_object_permission não é chamado automaticamente em APIView —
        # chamada explícita obrigatória aqui.
        self.check_object_permissions(request, grupo)

        try:
            despesa = criar_despesa(
                grupo=grupo,
                paid_by=request.user,
                created_by=request.user,
                description=data['description'],
                total_amount_cents=data['total_amount_cents'],
                split_type=data['split_type'],
                parcelas_data=data['parcelas'],
            )
        except PermissionError as e:
            raise PermissionDenied(str(e))
        except ValueError as e:
            raise ValidationError(str(e))

        despesa_detail = (
            Debt.objects
            .select_related('paid_by', 'created_by')
            .prefetch_related('installments__debtor')
            .get(pk=despesa.pk)
        )
        return Response(DespesaDetailSerializer(despesa_detail).data, status=status.HTTP_201_CREATED)


class DespesaDetailView(generics.RetrieveAPIView):
    """GET /api/despesas/{id}/ — detalhe com parcelas."""
    serializer_class = DespesaDetailSerializer

    def get_queryset(self):
        return (
            Debt.objects
            .filter(group_id__in=_grupos_do_user(self.request.user))
            .select_related('paid_by', 'created_by')
            .prefetch_related(
                'installments__debtor',
                'installments__comprovantes',
                'installments__charge_link',
            )
        )


class ParcelaDetailView(generics.RetrieveAPIView):
    """GET /api/parcelas/{id}/ — detalhe de parcela com comprovante e link."""
    serializer_class = ParcelaDetailSerializer

    def get_queryset(self):
        return (
            Installment.objects
            .filter(debt__group_id__in=_grupos_do_user(self.request.user))
            .select_related('debtor', 'debt__paid_by', 'charge_link')
            .prefetch_related('comprovantes')
        )
