import re

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.users.serializers import UserListSerializer
from .models import ContatoPendente, Group, GroupMember

User = get_user_model()

_E164_RE = re.compile(r'^\+\d{8,15}$')


class GrupoListSerializer(serializers.ModelSerializer):
    """Campos mínimos para listagem — card de grupo."""
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Group
        fields = ('id', 'name', 'emoji', 'archived', 'member_count')


class ContatoPendenteSerializer(serializers.ModelSerializer):
    """Representação de contato ainda não cadastrado."""

    class Meta:
        model = ContatoPendente
        # id é necessário para atribuir dívidas ao contato; telefone nunca é exposto.
        fields = ('id', 'name')


class MembroListSerializer(serializers.ModelSerializer):
    """Membro com dados do usuário ou do contato pendente."""
    user = UserListSerializer(read_only=True)
    contato_pendente = serializers.SerializerMethodField()

    class Meta:
        model = GroupMember
        fields = ('id', 'user', 'contato_pendente', 'role', 'status')

    def get_contato_pendente(self, obj):
        if not obj.contato_pendente:
            return None
        data = ContatoPendenteSerializer(obj.contato_pendente).data
        # Cada grupo pode ter seu próprio nome para o contato
        if obj.display_name:
            data['name'] = obj.display_name
        return data


class GrupoDetailSerializer(serializers.ModelSerializer):
    """Detalhe do grupo — apenas dados necessários para o frontend."""
    members = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ('id', 'name', 'emoji', 'archived', 'members')

    def get_members(self, obj):
        # Inativo: visível apenas para o grupo (com badge), mas o próprio inativo não vê
        request = self.context.get('request')
        qs = obj.members.select_related('user', 'contato_pendente')
        if request and request.user.is_authenticated:
            # Exclude members where the requesting user is inativo
            # (the inativo user themselves shouldn't see this group at all,
            # but others in the group can see them with the badge)
            qs = qs.exclude(
                user=request.user,
                status=GroupMember.STATUS_INATIVO,
            )
        return MembroListSerializer(qs, many=True).data


class GrupoFormSerializer(serializers.ModelSerializer):
    """Criação e edição de grupo."""

    class Meta:
        model = Group
        fields = ('name', 'emoji', 'archived')
        extra_kwargs = {'emoji': {'required': False}, 'archived': {'required': False}}


class AdicionarMembroSerializer(serializers.Serializer):
    """Adicionar membro ao grupo por número de telefone."""
    phone = serializers.CharField(max_length=20)
    name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=GroupMember.ROLE_CHOICES,
        default=GroupMember.ROLE_MEMBER,
        required=False,
    )

    def validate_phone(self, value):
        value = value.strip()
        if not _E164_RE.match(value):
            raise serializers.ValidationError(
                'Telefone deve estar no formato E.164 (ex: +5511999999999).'
            )
        return value

    def validate(self, data):
        group = self.context['group']
        phone = data['phone']

        # Busca usuário registrado com esse telefone (verificado)
        user = User.objects.filter(phone=phone, phone_verified=True).first()
        if user:
            if GroupMember.objects.filter(group=group, user=user).exists():
                raise serializers.ValidationError(
                    {'phone': ['Este usuário já é membro do grupo.']}
                )
            data['_resolved_user'] = user
            data['_resolved_contato'] = None
            return data

        # Busca contato pendente existente com esse telefone
        contato = ContatoPendente.objects.filter(phone=phone).first()
        if contato:
            if GroupMember.objects.filter(group=group, contato_pendente=contato).exists():
                raise serializers.ValidationError(
                    {'phone': ['Este contato já está no grupo.']}
                )
            data['_resolved_user'] = None
            data['_resolved_contato'] = contato
            return data

        # Novo contato — name obrigatório
        name = (data.get('name') or '').strip()
        if not name:
            raise serializers.ValidationError(
                {'name': ['Nome obrigatório para contatos ainda não cadastrados.']}
            )
        data['_resolved_user'] = None
        data['_resolved_contato'] = None
        return data
