from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.groups.models import Group, GroupMember
from .models import Debt, Installment
from .serializers import (
    DespesaDetailSerializer,
    DespesaEditSerializer,
    DespesaFormSerializer,
    DespesaListSerializer,
    ParcelaListSerializer,
)
from .services import criar_despesa, editar_despesa, excluir_despesa

_grupos_do_user = lambda user: GroupMember.objects.filter(
    user=user, status=GroupMember.STATUS_ATIVO
).values('group_id')


class DespesasPorGrupoView(generics.ListAPIView):
    """GET /api/grupos/{grupo_pk}/despesas/ — despesas de um grupo."""
    serializer_class = DespesaListSerializer
    pagination_class = None

    def get_queryset(self):
        grupo_pk = self.kwargs['grupo_pk']
        grupo = Group.objects.filter(
            pk=grupo_pk,
            members__user=self.request.user,
            members__status=GroupMember.STATUS_ATIVO,
        ).first()
        if not grupo:
            raise NotFound('Grupo não encontrado.')
        return (
            Debt.objects
            .filter(group=grupo)
            .select_related('paid_by')
            .prefetch_related('installments__debtor')
            .order_by('-created_at')
        )


class DespesaCreateView(APIView):
    """POST /api/despesas/ — cria despesa com parcelas atomicamente."""

    def post(self, request):
        serializer = DespesaFormSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        grupo = Group.objects.filter(
            pk=data['grupo_id'],
            members__user=request.user,
            members__status=GroupMember.STATUS_ATIVO,
        ).first()
        if not grupo:
            raise NotFound('Grupo não encontrado.')

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

        despesa_com_parcelas = (
            Debt.objects
            .select_related('paid_by')
            .prefetch_related('installments__debtor')
            .get(pk=despesa.pk)
        )
        return Response(DespesaListSerializer(despesa_com_parcelas).data, status=status.HTTP_201_CREATED)


class DespesaDetailView(generics.RetrieveAPIView):
    """
    GET    /api/despesas/{id}/ — detalhe com parcelas
    PATCH  /api/despesas/{id}/ — editar (só o credor; valores só se ninguém pagou)
    DELETE /api/despesas/{id}/ — excluir (só o credor; só se ninguém pagou)
    """
    serializer_class = DespesaDetailSerializer

    def get_queryset(self):
        return (
            Debt.objects
            .filter(group_id__in=_grupos_do_user(self.request.user))
            .select_related('paid_by', 'group')
            .prefetch_related(
                'installments__debtor',
                'installments__comprovantes',
                'installments__charge_link',
            )
        )

    def patch(self, request, *args, **kwargs):
        despesa = self.get_object()  # 404 se não for membro do grupo
        serializer = DespesaEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            editar_despesa(
                despesa=despesa,
                editor=request.user,
                description=data['description'],
                total_amount_cents=data.get('total_amount_cents'),
                split_type=data.get('split_type'),
                parcelas_data=data.get('parcelas'),
            )
        except PermissionError as e:
            raise PermissionDenied(str(e))
        except ValueError as e:
            raise ValidationError(str(e))
        atualizada = self.get_queryset().get(pk=despesa.pk)
        return Response(DespesaDetailSerializer(atualizada).data)

    def delete(self, request, *args, **kwargs):
        despesa = self.get_object()
        try:
            excluir_despesa(despesa=despesa, ator=request.user)
        except PermissionError as e:
            raise PermissionDenied(str(e))
        except ValueError as e:
            raise ValidationError(str(e))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ParcelaDetailView(generics.RetrieveAPIView):
    """GET /api/parcelas/{id}/ — detalhe de parcela com comprovante e link."""
    serializer_class = ParcelaListSerializer

    def get_queryset(self):
        return (
            Installment.objects
            .filter(debt__group_id__in=_grupos_do_user(self.request.user))
            .select_related('debtor', 'debt__paid_by', 'charge_link')
            .prefetch_related('comprovantes')
        )
