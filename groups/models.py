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


class GroupMember(models.Model):
    ROLE_ADMIN = 'admin'
    ROLE_MEMBER = 'member'
    ROLE_CHOICES = [(ROLE_ADMIN, 'Admin'), (ROLE_MEMBER, 'Membro')]

    id = models.BigAutoField(primary_key=True, db_column='mgp_id')
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name='members',
        db_column='mgp_grupo_id',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='group_memberships',
        db_column='mgp_usuario_id',
    )
    role = models.CharField(
        max_length=10, choices=ROLE_CHOICES, default=ROLE_MEMBER,
        db_column='mgp_papel',
    )
    joined_at = models.DateTimeField(auto_now_add=True, db_column='mgp_entrou_em')

    class Meta:
        db_table = 'membros_grupo'
        unique_together = ('group', 'user')
