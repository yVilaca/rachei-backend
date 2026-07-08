import uuid
from django.conf import settings
from django.db import models


class Group(models.Model):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False,
        db_column='grp_id',
    )
    name = models.CharField(max_length=120, db_column='grp_nome')
    emoji = models.CharField(max_length=8, blank=True, db_column='grp_emoji')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_groups',
        db_column='grp_criado_por_id',
    )
    archived = models.BooleanField(default=False, db_column='grp_arquivado', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_column='grp_criado_em')

    class Meta:
        db_table = 'grupos'

    def __str__(self):
        return self.name


class ContatoPendente(models.Model):
    """Pessoa adicionada a um grupo antes de ter conta no sistema."""
    id = models.BigAutoField(primary_key=True, db_column='ctp_id')
    phone = models.CharField(max_length=20, unique=True, db_column='ctp_telefone')
    name = models.CharField(max_length=150, db_column='ctp_nome')
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='contatos_pendentes',
        db_column='ctp_criado_por_id',
    )
    criado_em = models.DateTimeField(auto_now_add=True, db_column='ctp_criado_em')

    class Meta:
        db_table = 'contatos_pendentes'

    def __str__(self):
        return f'{self.name} ({self.phone})'


class GroupMember(models.Model):
    ROLE_ADMIN = 'admin'
    ROLE_MEMBER = 'member'
    ROLE_CHOICES = [(ROLE_ADMIN, 'Admin'), (ROLE_MEMBER, 'Membro')]

    STATUS_ATIVO = 'ativo'
    STATUS_INATIVO = 'inativo'
    STATUS_PENDENTE_CONFIRMACAO = 'pendente_confirmacao'
    STATUS_PENDENTE_REGISTRO = 'pendente_registro'
    STATUS_CHOICES = [
        (STATUS_ATIVO, 'Ativo'),
        (STATUS_INATIVO, 'Inativo'),
        (STATUS_PENDENTE_CONFIRMACAO, 'Aguardando confirmação'),
        (STATUS_PENDENTE_REGISTRO, 'Aguardando cadastro'),
    ]

    id = models.BigAutoField(primary_key=True, db_column='mgp_id')
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name='members',
        db_column='mgp_grupo_id',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='group_memberships',
        db_column='mgp_usuario_id',
    )
    contato_pendente = models.ForeignKey(
        ContatoPendente,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='group_memberships',
        db_column='mgp_contato_pendente_id',
    )
    role = models.CharField(
        max_length=10, choices=ROLE_CHOICES, default=ROLE_MEMBER,
        db_column='mgp_papel',
    )
    status = models.CharField(
        max_length=25, choices=STATUS_CHOICES, default=STATUS_ATIVO,
        db_column='mgp_status',
    )
    adicionado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='membros_adicionados',
        db_column='mgp_adicionado_por_id',
    )
    display_name = models.CharField(
        max_length=150, blank=True, db_column='mgp_nome_exibicao',
    )
    joined_at = models.DateTimeField(auto_now_add=True, db_column='mgp_entrou_em')

    class Meta:
        db_table = 'membros_grupo'
        # Uniqueness handled at application layer:
        # - one GroupMember per (group, user) when user is set
        # - one GroupMember per (group, contato_pendente) when contato_pendente is set
