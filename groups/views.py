from django.db.models import Count, Prefetch
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import Group, GroupMember
from .serializers import (
    GrupoDetailSerializer,
    GrupoFormSerializer,
    GrupoListSerializer,
    MembroFormSerializer,
    MembroListSerializer,
)


def _get_grupo(grupo_id, user, require_admin=False):
    """Retorna o grupo se o user for membro (e opcionalmente admin)."""
    qs = Group.objects.filter(pk=grupo_id, members__user=user)
    if require_admin:
        qs = qs.filter(members__role=GroupMember.ROLE_ADMIN)
    grupo = qs.first()
    if not grupo:
        raise NotFound('Grupo não encontrado.')
    return grupo


class GrupoListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/grupos/ — lista grupos do usuário autenticado
    POST /api/grupos/ — cria novo grupo (criador vira admin automaticamente)
    """

    def get_serializer_class(self):
        return GrupoFormSerializer if self.request.method == 'POST' else GrupoListSerializer

    def get_queryset(self):
        return (
            Group.objects
            .filter(members__user=self.request.user)
            .annotate(member_count=Count('members'))
            .order_by('archived', '-created_at')
        )

    def create(self, request, *args, **kwargs):
        serializer = GrupoFormSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = serializer.save(created_by=request.user)
        GroupMember.objects.create(group=group, user=request.user, role=GroupMember.ROLE_ADMIN)
        return Response(GrupoDetailSerializer(group).data, status=status.HTTP_201_CREATED)


class GrupoDetailView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/grupos/{id}/ — detalhe do grupo com membros
    PATCH /api/grupos/{id}/ — editar (somente admins)
    """
    http_method_names = ['get', 'patch']

    def get_serializer_class(self):
        return GrupoFormSerializer if self.request.method == 'PATCH' else GrupoDetailSerializer

    def get_object(self):
        require_admin = self.request.method == 'PATCH'
        grupo = _get_grupo(self.kwargs['pk'], self.request.user, require_admin=require_admin)

        if self.request.method == 'GET':
            grupo = (
                Group.objects
                .prefetch_related(
                    Prefetch('members', queryset=GroupMember.objects.select_related('user'))
                )
                .select_related('created_by')
                .get(pk=grupo.pk)
            )
        return grupo


class MembroListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/grupos/{grupo_pk}/membros/ — lista membros
    POST /api/grupos/{grupo_pk}/membros/ — adiciona membro (somente admins)
    """

    def get_serializer_class(self):
        return MembroFormSerializer if self.request.method == 'POST' else MembroListSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['group'] = _get_grupo(self.kwargs['grupo_pk'], self.request.user)
        return ctx

    def get_queryset(self):
        _get_grupo(self.kwargs['grupo_pk'], self.request.user)
        return (
            GroupMember.objects
            .filter(group_id=self.kwargs['grupo_pk'])
            .select_related('user')
            .order_by('joined_at')
        )

    def perform_create(self, serializer):
        grupo = _get_grupo(self.kwargs['grupo_pk'], self.request.user, require_admin=True)
        serializer.save(group=grupo)


class MembroDestroyView(generics.DestroyAPIView):
    """DELETE /api/grupos/{grupo_pk}/membros/{user_pk}/ — remove membro (somente admins)."""

    def get_object(self):
        grupo = _get_grupo(self.kwargs['grupo_pk'], self.request.user, require_admin=True)
        try:
            return GroupMember.objects.get(group=grupo, user_id=self.kwargs['user_pk'])
        except GroupMember.DoesNotExist:
            raise NotFound('Membro não encontrado.')

    def perform_destroy(self, instance):
        if instance.role == GroupMember.ROLE_ADMIN:
            outros_admins = GroupMember.objects.filter(
                group=instance.group, role=GroupMember.ROLE_ADMIN
            ).exclude(pk=instance.pk).exists()
            if not outros_admins:
                raise ValidationError('Não é possível remover o único administrador do grupo.')
        instance.delete()
