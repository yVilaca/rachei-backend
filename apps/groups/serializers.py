from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.users.serializers import UserListSerializer
from .models import Group, GroupMember

User = get_user_model()


class GrupoListSerializer(serializers.ModelSerializer):
    """Campos mínimos para listagem — card de grupo."""
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Group
        fields = ('id', 'name', 'emoji', 'archived', 'created_at', 'member_count')


class MembroListSerializer(serializers.ModelSerializer):
    """Membro com dados do usuário aninhados."""
    user = UserListSerializer(read_only=True)

    class Meta:
        model = GroupMember
        fields = ('id', 'user', 'role', 'joined_at')


class GrupoDetailSerializer(serializers.ModelSerializer):
    """Detalhe completo — inclui membros e criador."""
    members = MembroListSerializer(many=True, read_only=True)
    created_by = UserListSerializer(read_only=True)

    class Meta:
        model = Group
        fields = ('id', 'name', 'emoji', 'archived', 'created_at', 'created_by', 'members')


class GrupoFormSerializer(serializers.ModelSerializer):
    """Criação e edição de grupo."""

    class Meta:
        model = Group
        fields = ('name', 'emoji', 'archived')
        extra_kwargs = {'emoji': {'required': False}, 'archived': {'required': False}}


class MembroFormSerializer(serializers.ModelSerializer):
    """Adicionar membro ao grupo."""
    user_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), source='user')

    class Meta:
        model = GroupMember
        fields = ('user_id', 'role')
        extra_kwargs = {'role': {'required': False, 'default': GroupMember.ROLE_MEMBER}}

    def validate(self, data):
        group = self.context['group']
        if GroupMember.objects.filter(group=group, user=data['user']).exists():
            raise serializers.ValidationError('Usuário já é membro do grupo.')
        return data
