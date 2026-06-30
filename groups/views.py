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
    if require_admin:
        filter_kwargs = {'members__user': user, 'members__role': GroupMember.ROLE_ADMIN}
    else:
        filter_kwargs = {'members__user': user}
    grupo = Group.objects.filter(pk=grupo_id, **filter_kwargs).first()
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
            .annotate(member_count=Count('members', distinct=True))
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
        if self.request.method == 'PATCH':
            member_filter = {'members__user': self.request.user, 'members__role': GroupMember.ROLE_ADMIN}
        else:
            member_filter = {'members__user': self.request.user}
        grupo = (
            Group.objects
            .filter(pk=self.kwargs['pk'], **member_filter)
            .select_related('created_by')
            .prefetch_related(
                Prefetch('members', queryset=GroupMember.objects.select_related('user'))
            )
            .first()
        )
        if not grupo:
            raise NotFound('Grupo não encontrado.')
        return grupo


class MembroListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/grupos/{grupo_pk}/membros/ — lista membros
    POST /api/grupos/{grupo_pk}/membros/ — adiciona membro (somente admins)
    """

    def get_serializer_class(self):
        return MembroFormSerializer if self.request.method == 'POST' else MembroListSerializer

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
            .select_related('user')
            .order_by('joined_at')
        )

    def perform_create(self, serializer):
        grupo = self._grupo_cached()
        if not GroupMember.objects.filter(group=grupo, user=self.request.user, role=GroupMember.ROLE_ADMIN).exists():
            raise PermissionDenied('Somente administradores podem adicionar membros.')
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
