"""
Testes de controle de acesso — grupos, membros e despesas.

Comportamento padrão do projeto:
- Outsider (não-membro): 404 — esconde existência do recurso
- Membro sem permissão suficiente (ex: não-admin): 403
- Não autenticado: 401
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Group, GroupMember

User = get_user_model()


def _make_user(email, password='TestPass123!'):
    return User.objects.create_user(username=email, email=email, password=password)


def _make_group(owner):
    group = Group.objects.create(name='Grupo Teste', created_by=owner)
    GroupMember.objects.create(group=group, user=owner, role=GroupMember.ROLE_ADMIN)
    return group


def _token(user):
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)


# ---------------------------------------------------------------------------
# 1. IsGroupMember — DespesaCreateView (APIView com check_object_permissions)
# ---------------------------------------------------------------------------

class DespesaCreatePermissionTest(TestCase):
    """
    Verifica que DespesaCreateView retorna 404 para não-membros (esconde existência do grupo).
    Membership verificada por queryset filtering, consistente com o restante do projeto.
    """

    def setUp(self):
        self.owner = _make_user('owner@test.com')
        self.outsider = _make_user('outsider@test.com')
        self.group = _make_group(self.owner)
        self.client = APIClient()

    def _payload(self):
        return {
            'grupo_id': str(self.group.pk),
            'description': 'Almoço',
            'total_amount_cents': 10000,
            'split_type': 'equal',
            'parcelas': [{'debtor_id': self.owner.pk, 'amount_cents': 10000}],
        }

    def test_non_member_gets_404(self):
        """Não-membro tenta criar despesa no grupo → 404 (grupo não encontrado no queryset)."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.outsider)}')
        r = self.client.post('/api/despesas/', self._payload(), format='json')
        self.assertEqual(
            r.status_code, 404,
            f'Esperado 404, recebido {r.status_code}: {r.data}'
        )

    def test_member_can_create_despesa(self):
        """Membro do grupo consegue criar despesa — 201."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.owner)}')
        r = self.client.post('/api/despesas/', self._payload(), format='json')
        self.assertEqual(
            r.status_code, 201,
            f'Esperado 201, recebido {r.status_code}: {r.data}'
        )

    def test_unauthenticated_gets_401(self):
        """Sem token → 401 (IsAuthenticated do default)."""
        r = self.client.post('/api/despesas/', self._payload(), format='json')
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# 2. IsGroupAdmin — MembroListCreateView POST (get_permissions + check_object_permissions)
# ---------------------------------------------------------------------------

class MembroAddPermissionTest(TestCase):
    """
    Verifica que POST /membros/ retorna 403 para membros comuns.
    IsGroupAdmin é retornado por get_permissions() para POST,
    e has_object_permission é chamado via check_object_permissions em perform_create.
    """

    def setUp(self):
        self.admin = _make_user('admin@test.com')
        self.member = _make_user('member@test.com')
        self.outsider = _make_user('outsider@test.com')
        self.new_user = _make_user('new@test.com')
        self.group = _make_group(self.admin)
        GroupMember.objects.create(group=self.group, user=self.member, role=GroupMember.ROLE_MEMBER)
        self.client = APIClient()
        self.url = f'/api/grupos/{self.group.pk}/membros/'

    def test_non_admin_member_cannot_add_member(self):
        """Membro comum (não admin) tenta adicionar membro → 403."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.member)}')
        r = self.client.post(self.url, {'user_id': self.new_user.pk}, format='json')
        self.assertEqual(
            r.status_code, 403,
            f'Esperado 403, recebido {r.status_code}: {r.data}'
        )

    def test_admin_can_add_member(self):
        """Admin consegue adicionar membro → 201."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.admin)}')
        r = self.client.post(self.url, {'user_id': self.new_user.pk}, format='json')
        self.assertEqual(
            r.status_code, 201,
            f'Esperado 201, recebido {r.status_code}: {r.data}'
        )

    def test_member_can_list_members(self):
        """GET /membros/ funciona para qualquer membro — não exige admin."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.member)}')
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)

    def test_outsider_cannot_list_members(self):
        """Não-membro em GET /membros/ → 404 (grupo não aparece no queryset)."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.outsider)}')
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# 3. MembroDestroyView — membro comum tenta DELETE
# ---------------------------------------------------------------------------

class MembroDestroyPermissionTest(TestCase):
    """
    Verifica que DELETE /membros/{pk}/ retorna 403 para membros sem role admin
    e 404 para outsiders (não-membros).
    """

    def setUp(self):
        self.admin = _make_user('admin2@test.com')
        self.member = _make_user('member2@test.com')
        self.outsider = _make_user('outsider2@test.com')
        self.target = _make_user('target@test.com')
        self.group = _make_group(self.admin)
        GroupMember.objects.create(group=self.group, user=self.member, role=GroupMember.ROLE_MEMBER)
        GroupMember.objects.create(group=self.group, user=self.target, role=GroupMember.ROLE_MEMBER)
        self.client = APIClient()

    def test_non_admin_member_delete_gets_403(self):
        """Membro comum tenta remover outro membro (não o último admin) → 403."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.member)}')
        url = f'/api/grupos/{self.group.pk}/membros/{self.target.pk}/'
        r = self.client.delete(url)
        self.assertEqual(
            r.status_code, 403,
            f'Esperado 403, recebido {r.status_code}: {r.data}'
        )
        self.assertTrue(
            GroupMember.objects.filter(group=self.group, user=self.target).exists(),
            'Membro foi removido indevidamente por não-admin.'
        )

    def test_unauthenticated_post_membros_gets_401(self):
        """
        POST /membros/ sem autenticação → 401.
        Verifica que get_permissions() inclui IsAuthenticated antes de IsGroupAdmin,
        impedindo que AnonymousUser chegue ao has_object_permission (evita TypeError).
        """
        url = f'/api/grupos/{self.group.pk}/membros/'
        r = self.client.post(url, {'user_id': self.outsider.pk}, format='json')
        self.assertEqual(
            r.status_code, 401,
            f'Esperado 401, recebido {r.status_code}: {r.data}'
        )


# ---------------------------------------------------------------------------
# 4. Último admin — não pode ser removido
# ---------------------------------------------------------------------------

class LastAdminProtectionTest(TestCase):
    """Verifica que remover o único admin do grupo é bloqueado."""

    def setUp(self):
        self.admin = _make_user('lastadmin@test.com')
        self.group = _make_group(self.admin)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.admin)}')

    def test_cannot_remove_last_admin(self):
        """DELETE do único admin → 400."""
        url = f'/api/grupos/{self.group.pk}/membros/{self.admin.pk}/'
        r = self.client.delete(url)
        self.assertEqual(
            r.status_code, 400,
            f'Esperado 400, recebido {r.status_code}: {r.data}'
        )
        self.assertTrue(
            GroupMember.objects.filter(group=self.group, user=self.admin).exists(),
            'Admin foi removido indevidamente.'
        )

    def test_can_remove_non_last_admin(self):
        """Com dois admins, pode remover um → 204."""
        second_admin = _make_user('second_admin@test.com')
        GroupMember.objects.create(group=self.group, user=second_admin, role=GroupMember.ROLE_ADMIN)
        url = f'/api/grupos/{self.group.pk}/membros/{second_admin.pk}/'
        r = self.client.delete(url)
        self.assertEqual(r.status_code, 204)
