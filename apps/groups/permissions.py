from rest_framework.permissions import BasePermission

from .models import GroupMember


class IsGroupMember(BasePermission):
    """
    Permite acesso somente se request.user for membro ATIVO do grupo.

    Projetada para uso explícito via check_object_permissions(request, grupo)
    em APIViews — has_object_permission NÃO é chamado automaticamente fora
    de generic views que usam get_object().
    """
    message = 'Você não é membro deste grupo.'

    def has_object_permission(self, request, view, obj):
        return GroupMember.objects.filter(
            group=obj,
            user=request.user,
            status=GroupMember.STATUS_ATIVO,
        ).exists()


class IsGroupAdmin(BasePermission):
    """
    Permite acesso somente se request.user for administrador ATIVO do grupo.

    Mesma observação: chamar check_object_permissions(request, grupo)
    explicitamente em APIViews.
    """
    message = 'Somente administradores podem realizar esta operação.'

    def has_object_permission(self, request, view, obj):
        return GroupMember.objects.filter(
            group=obj,
            user=request.user,
            role=GroupMember.ROLE_ADMIN,
            status=GroupMember.STATUS_ATIVO,
        ).exists()
