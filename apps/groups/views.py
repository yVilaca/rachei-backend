from django.db.models import Count, Prefetch
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ContatoPendente, Group, GroupMember
from .permissions import IsGroupAdmin, IsGroupMember
from .serializers import (
    AdicionarMembroSerializer,
    GrupoDetailSerializer,
    GrupoFormSerializer,
    GrupoListSerializer,
    MembroListSerializer,
)


def _get_grupo(grupo_id, user, require_admin=False):
    """Retorna grupo se o user for membro ativo (e opcionalmente admin). 404 caso contrário."""
    if require_admin:
        filter_kwargs = {
            'members__user': user,
            'members__role': GroupMember.ROLE_ADMIN,
            'members__status': GroupMember.STATUS_ATIVO,
        }
    else:
        filter_kwargs = {
            'members__user': user,
            'members__status__in': [
                GroupMember.STATUS_ATIVO,
                GroupMember.STATUS_PENDENTE_CONFIRMACAO,
            ],
        }
    grupo = Group.objects.filter(pk=grupo_id, **filter_kwargs).first()
    if not grupo:
        raise NotFound('Grupo não encontrado.')
    return grupo


class GrupoListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/grupos/ — lista grupos do usuário autenticado (apenas ativos)
    POST /api/grupos/ — cria novo grupo (criador vira admin automaticamente)
    """

    def get_serializer_class(self):
        return GrupoFormSerializer if self.request.method == 'POST' else GrupoListSerializer

    def get_queryset(self):
        return (
            Group.objects
            .filter(
                members__user=self.request.user,
                members__status=GroupMember.STATUS_ATIVO,
            )
            .annotate(member_count=Count('members', distinct=True))
            .order_by('archived', '-created_at')
        )

    def create(self, request, *args, **kwargs):
        serializer = GrupoFormSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = serializer.save(created_by=request.user)
        GroupMember.objects.create(
            group=group, user=request.user,
            role=GroupMember.ROLE_ADMIN, status=GroupMember.STATUS_ATIVO,
            adicionado_por=request.user,
        )
        return Response(GrupoDetailSerializer(group).data, status=status.HTTP_201_CREATED)


class GrupoDetailView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/grupos/{id}/ — detalhe do grupo com membros
    PATCH /api/grupos/{id}/ — editar (somente admins ativos)
    """
    http_method_names = ['get', 'patch']

    def get_serializer_class(self):
        return GrupoFormSerializer if self.request.method == 'PATCH' else GrupoDetailSerializer

    def get_object(self):
        if self.request.method == 'PATCH':
            member_filter = {
                'members__user': self.request.user,
                'members__role': GroupMember.ROLE_ADMIN,
                'members__status': GroupMember.STATUS_ATIVO,
            }
        else:
            member_filter = {
                'members__user': self.request.user,
                'members__status__in': [
                    GroupMember.STATUS_ATIVO,
                    GroupMember.STATUS_PENDENTE_CONFIRMACAO,
                ],
            }
        grupo = (
            Group.objects
            .filter(pk=self.kwargs['pk'], **member_filter)
            .select_related('created_by')
            .prefetch_related(
                Prefetch(
                    'members',
                    queryset=GroupMember.objects.select_related('user', 'contato_pendente'),
                )
            )
            .first()
        )
        if not grupo:
            raise NotFound('Grupo não encontrado.')
        return grupo


class MembroListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/grupos/{grupo_pk}/membros/ — lista membros
    POST /api/grupos/{grupo_pk}/membros/ — adiciona membro por telefone (somente admins)
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.IsAuthenticated(), IsGroupAdmin()]
        return super().get_permissions()

    def get_serializer_class(self):
        return AdicionarMembroSerializer if self.request.method == 'POST' else MembroListSerializer

    def _grupo_cached(self):
        if not hasattr(self, '_grupo'):
            self._grupo = _get_grupo(self.kwargs['grupo_pk'], self.request.user)
        return self._grupo

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['group'] = self._grupo_cached()
        return ctx

    def get_queryset(self):
        grupo = self._grupo_cached()
        return (
            GroupMember.objects
            .filter(group=grupo)
            .select_related('user', 'contato_pendente')
            .order_by('joined_at')
        )

    def create(self, request, *args, **kwargs):
        grupo = self._grupo_cached()
        self.check_object_permissions(request, grupo)

        serializer = AdicionarMembroSerializer(
            data=request.data,
            context={'group': grupo, 'request': request},
        )
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        resolved_user = vd.get('_resolved_user')
        resolved_contato = vd.get('_resolved_contato')
        phone = vd['phone']
        role = vd.get('role', GroupMember.ROLE_MEMBER)

        if resolved_user:
            # Usuário já cadastrado → entra como ativo imediatamente
            member = GroupMember.objects.create(
                group=grupo,
                user=resolved_user,
                role=role,
                status=GroupMember.STATUS_ATIVO,
                adicionado_por=request.user,
            )
        elif resolved_contato:
            # Contato pendente já existe → reutiliza
            member = GroupMember.objects.create(
                group=grupo,
                contato_pendente=resolved_contato,
                role=role,
                status=GroupMember.STATUS_PENDENTE_REGISTRO,
                adicionado_por=request.user,
            )
        else:
            # Novo contato → cria ContatoPendente
            name = vd['name'].strip()
            contato = ContatoPendente.objects.create(
                phone=phone,
                name=name,
                criado_por=request.user,
            )
            member = GroupMember.objects.create(
                group=grupo,
                contato_pendente=contato,
                role=role,
                status=GroupMember.STATUS_PENDENTE_REGISTRO,
                adicionado_por=request.user,
            )

        return Response(
            MembroListSerializer(member).data,
            status=status.HTTP_201_CREATED,
        )


class MembroDestroyView(generics.DestroyAPIView):
    """DELETE /api/grupos/{grupo_pk}/membros/{member_pk}/ — remove membro (somente admins)."""

    permission_classes = [permissions.IsAuthenticated, IsGroupAdmin]

    def get_object(self):
        grupo = _get_grupo(self.kwargs['grupo_pk'], self.request.user, require_admin=False)
        self.check_object_permissions(self.request, grupo)
        try:
            return GroupMember.objects.get(pk=self.kwargs['member_pk'], group=grupo)
        except GroupMember.DoesNotExist:
            raise NotFound('Membro não encontrado.')

    def perform_destroy(self, instance):
        if instance.role == GroupMember.ROLE_ADMIN and instance.user:
            outros_admins = GroupMember.objects.filter(
                group=instance.group,
                role=GroupMember.ROLE_ADMIN,
                status=GroupMember.STATUS_ATIVO,
            ).exclude(pk=instance.pk).exists()
            if not outros_admins:
                raise ValidationError('Não é possível remover o único administrador do grupo.')
        instance.delete()


class GruposPendentesView(APIView):
    """GET /api/me/grupos-pendentes/ — grupos aguardando confirmação do usuário."""

    def get(self, request):
        memberships = (
            GroupMember.objects
            .filter(user=request.user, status=GroupMember.STATUS_PENDENTE_CONFIRMACAO)
            .select_related('group', 'adicionado_por')
        )
        data = []
        for m in memberships:
            adicionado_por = None
            if m.adicionado_por:
                adicionado_por = {
                    'id': m.adicionado_por.id,
                    'name': m.adicionado_por.get_full_name() or m.adicionado_por.username,
                }
            data.append({
                'membership_id': m.id,
                'group': {
                    'id': str(m.group.id),
                    'name': m.group.name,
                    'emoji': m.group.emoji,
                },
                'adicionado_por': adicionado_por,
            })
        return Response(data)


class ConfirmarParticipacaoView(APIView):
    """POST /api/grupos/{grupo_pk}/confirmar/ — confirma ou nega participação no grupo."""

    def post(self, request, grupo_pk):
        aceitar = request.data.get('aceitar')
        if aceitar is None:
            raise ValidationError({'aceitar': ['Campo obrigatório (true ou false).']})

        membership = (
            GroupMember.objects
            .filter(
                group_id=grupo_pk,
                user=request.user,
                status__in=[
                    GroupMember.STATUS_PENDENTE_CONFIRMACAO,
                    GroupMember.STATUS_ATIVO,
                ],
            )
            .first()
        )
        if not membership:
            raise NotFound('Participação não encontrada.')

        if aceitar:
            membership.status = GroupMember.STATUS_ATIVO
            membership.save(update_fields=['status'])
            return Response({'detail': 'Participação confirmada.'})
        else:
            membership.status = GroupMember.STATUS_INATIVO
            membership.save(update_fields=['status'])
            return Response({'detail': 'Participação negada.'})
