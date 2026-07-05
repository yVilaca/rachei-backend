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

from .models import ContatoPendente, Group, GroupMember

User = get_user_model()


def _make_user(email, password='TestPass123!', phone=None, phone_verified=False):
    return User.objects.create_user(
        username=email, email=email, password=password,
        phone=phone, phone_verified=phone_verified,
    )


def _make_group(owner):
    group = Group.objects.create(name='Grupo Teste', created_by=owner)
    GroupMember.objects.create(
        group=group, user=owner,
        role=GroupMember.ROLE_ADMIN, status=GroupMember.STATUS_ATIVO,
        adicionado_por=owner,
    )
    return group


def _token(user):
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)


# ---------------------------------------------------------------------------
# 1. DespesaCreateView — membership via queryset filtering
# ---------------------------------------------------------------------------

class DespesaCreatePermissionTest(TestCase):
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
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.outsider)}')
        r = self.client.post('/api/despesas/', self._payload(), format='json')
        self.assertEqual(r.status_code, 404, f'Esperado 404, recebido {r.status_code}: {r.data}')

    def test_member_can_create_despesa(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.owner)}')
        r = self.client.post('/api/despesas/', self._payload(), format='json')
        self.assertEqual(r.status_code, 201, f'Esperado 201, recebido {r.status_code}: {r.data}')

    def test_unauthenticated_gets_401(self):
        r = self.client.post('/api/despesas/', self._payload(), format='json')
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# 2. MembroListCreateView POST — adicionar membro por telefone
# ---------------------------------------------------------------------------

class MembroAddPermissionTest(TestCase):
    def setUp(self):
        self.admin = _make_user('admin@test.com')
        self.member = _make_user('member@test.com')
        self.outsider = _make_user('outsider@test.com')
        self.new_user = _make_user(
            'new@test.com',
            phone='+5511900000001',
            phone_verified=True,
        )
        self.group = _make_group(self.admin)
        GroupMember.objects.create(
            group=self.group, user=self.member,
            role=GroupMember.ROLE_MEMBER, status=GroupMember.STATUS_ATIVO,
        )
        self.client = APIClient()
        self.url = f'/api/grupos/{self.group.pk}/membros/'

    def test_non_admin_member_cannot_add_member(self):
        """Membro comum tenta adicionar → 403 (antes de validar o payload)."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.member)}')
        r = self.client.post(self.url, {'phone': '+5511900000001'}, format='json')
        self.assertEqual(r.status_code, 403, f'Esperado 403, recebido {r.status_code}: {r.data}')

    def test_admin_can_add_existing_user_by_phone(self):
        """Admin adiciona usuário existente pelo telefone verificado → 201, status ativo."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.admin)}')
        r = self.client.post(self.url, {'phone': '+5511900000001'}, format='json')
        self.assertEqual(r.status_code, 201, f'Esperado 201, recebido {r.status_code}: {r.data}')
        self.assertEqual(r.data['status'], GroupMember.STATUS_ATIVO)
        self.assertIsNotNone(r.data['user'])

    def test_admin_can_add_new_contact_by_phone(self):
        """Admin adiciona telefone não cadastrado → 201, status pendente_registro, contato criado."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.admin)}')
        r = self.client.post(self.url, {'phone': '+5511999990000', 'name': 'João'}, format='json')
        self.assertEqual(r.status_code, 201, f'Esperado 201, recebido {r.status_code}: {r.data}')
        self.assertEqual(r.data['status'], GroupMember.STATUS_PENDENTE_REGISTRO)
        self.assertIsNone(r.data['user'])
        self.assertIsNotNone(r.data['contato_pendente'])
        self.assertTrue(ContatoPendente.objects.filter(phone='+5511999990000').exists())

    def test_add_new_contact_without_name_returns_400(self):
        """Adicionar telefone desconhecido sem nome → 400."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.admin)}')
        r = self.client.post(self.url, {'phone': '+5511999990001'}, format='json')
        self.assertEqual(r.status_code, 400, f'Esperado 400, recebido {r.status_code}: {r.data}')

    def test_add_duplicate_user_returns_400(self):
        """Adicionar usuário que já é membro → 400."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.admin)}')
        # Adiciona member pelo telefone (mas member não tem phone verificado)
        # Usa o admin que já é membro:
        r = self.client.post(self.url, {'phone': '+5511900000001'}, format='json')
        self.assertEqual(r.status_code, 201)
        # Tenta adicionar novamente
        r2 = self.client.post(self.url, {'phone': '+5511900000001'}, format='json')
        self.assertEqual(r2.status_code, 400)

    def test_member_can_list_members(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.member)}')
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)

    def test_outsider_cannot_list_members(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.outsider)}')
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 404)

    def test_unauthenticated_post_membros_gets_401(self):
        r = self.client.post(self.url, {'phone': '+5511900000001'}, format='json')
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# 3. MembroDestroyView — usa member_pk (GroupMember.id)
# ---------------------------------------------------------------------------

class MembroDestroyPermissionTest(TestCase):
    def setUp(self):
        self.admin = _make_user('admin2@test.com')
        self.member = _make_user('member2@test.com')
        self.outsider = _make_user('outsider2@test.com')
        self.target = _make_user('target@test.com')
        self.group = _make_group(self.admin)
        GroupMember.objects.create(
            group=self.group, user=self.member,
            role=GroupMember.ROLE_MEMBER, status=GroupMember.STATUS_ATIVO,
        )
        self.target_membership = GroupMember.objects.create(
            group=self.group, user=self.target,
            role=GroupMember.ROLE_MEMBER, status=GroupMember.STATUS_ATIVO,
        )
        self.client = APIClient()

    def _delete_url(self, membership):
        return f'/api/grupos/{self.group.pk}/membros/{membership.pk}/'

    def test_non_admin_member_delete_gets_403(self):
        """Membro comum tenta remover outro membro → 403."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.member)}')
        r = self.client.delete(self._delete_url(self.target_membership))
        self.assertEqual(r.status_code, 403, f'Esperado 403, recebido {r.status_code}: {r.data}')
        self.assertTrue(GroupMember.objects.filter(pk=self.target_membership.pk).exists())

    def test_unauthenticated_post_membros_gets_401(self):
        url = f'/api/grupos/{self.group.pk}/membros/'
        r = self.client.post(url, {'phone': '+5511000000000'}, format='json')
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# 4. Último admin — proteção
# ---------------------------------------------------------------------------

class LastAdminProtectionTest(TestCase):
    def setUp(self):
        self.admin = _make_user('lastadmin@test.com')
        self.group = _make_group(self.admin)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.admin)}')
        self.admin_membership = GroupMember.objects.get(group=self.group, user=self.admin)

    def _delete_url(self, membership):
        return f'/api/grupos/{self.group.pk}/membros/{membership.pk}/'

    def test_cannot_remove_last_admin(self):
        """DELETE do único admin → 400."""
        r = self.client.delete(self._delete_url(self.admin_membership))
        self.assertEqual(r.status_code, 400, f'Esperado 400, recebido {r.status_code}: {r.data}')
        self.assertTrue(GroupMember.objects.filter(pk=self.admin_membership.pk).exists())

    def test_can_remove_non_last_admin(self):
        """Com dois admins, pode remover um → 204."""
        second_admin = _make_user('second_admin@test.com')
        second_membership = GroupMember.objects.create(
            group=self.group, user=second_admin,
            role=GroupMember.ROLE_ADMIN, status=GroupMember.STATUS_ATIVO,
        )
        r = self.client.delete(self._delete_url(second_membership))
        self.assertEqual(r.status_code, 204)


# ---------------------------------------------------------------------------
# 5. Fluxo de confirmação de participação
# ---------------------------------------------------------------------------

class ConfirmarParticipacaoTest(TestCase):
    def setUp(self):
        self.admin = _make_user('admin3@test.com')
        self.group = _make_group(self.admin)
        self.user = _make_user('invited@test.com')
        self.membership = GroupMember.objects.create(
            group=self.group,
            user=self.user,
            role=GroupMember.ROLE_MEMBER,
            status=GroupMember.STATUS_PENDENTE_CONFIRMACAO,
            adicionado_por=self.admin,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.user)}')
        self.url = f'/api/grupos/{self.group.pk}/confirmar/'

    def test_confirmar_aceita_participacao(self):
        """aceitar=true → status ativo."""
        r = self.client.post(self.url, {'aceitar': True}, format='json')
        self.assertEqual(r.status_code, 200, f'{r.data}')
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, GroupMember.STATUS_ATIVO)

    def test_confirmar_nega_participacao(self):
        """aceitar=false → status inativo."""
        r = self.client.post(self.url, {'aceitar': False}, format='json')
        self.assertEqual(r.status_code, 200, f'{r.data}')
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, GroupMember.STATUS_INATIVO)

    def test_inativo_nao_ve_grupo_na_lista(self):
        """Usuário inativo não vê o grupo em GET /api/grupos/."""
        self.membership.status = GroupMember.STATUS_INATIVO
        self.membership.save()
        r = self.client.get('/api/grupos/')
        self.assertEqual(r.status_code, 200)
        # A API usa paginação: r.data tem 'results'
        grupos = r.data.get('results', r.data) if isinstance(r.data, dict) else r.data
        ids = [str(g['id']) for g in grupos]
        self.assertNotIn(str(self.group.pk), ids)


# ---------------------------------------------------------------------------
# 6. Contato pendente → link ao se cadastrar
# ---------------------------------------------------------------------------

class ContatoPendenteLinkTest(TestCase):
    def setUp(self):
        self.admin = _make_user('admin4@test.com')
        self.group = _make_group(self.admin)
        # Cria contato pendente com telefone
        self.contato = ContatoPendente.objects.create(
            phone='+5511988880000',
            name='Maria',
            criado_por=self.admin,
        )
        GroupMember.objects.create(
            group=self.group,
            contato_pendente=self.contato,
            role=GroupMember.ROLE_MEMBER,
            status=GroupMember.STATUS_PENDENTE_REGISTRO,
            adicionado_por=self.admin,
        )
        # Registra usuário com mesmo telefone (simulando verify_phone)
        self.new_user = _make_user('maria@test.com', phone='+5511988880000', phone_verified=False)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {_token(self.new_user)}')

    def test_verify_phone_linka_contatos_pendentes(self):
        """Verificar OTP com telefone de contato pendente → migra membros para pendente_confirmacao."""
        from apps.users.models import SmsVerification
        code = SmsVerification.generate(self.new_user)
        r = self.client.post('/api/auth/phone/verify/', {'code': code}, format='json')
        self.assertEqual(r.status_code, 200, f'{r.data}')
        # Contato pendente deve ter sido deletado
        self.assertFalse(ContatoPendente.objects.filter(pk=self.contato.pk).exists())
        # GroupMember deve ter user e status pendente_confirmacao
        m = GroupMember.objects.get(group=self.group, user=self.new_user)
        self.assertEqual(m.status, GroupMember.STATUS_PENDENTE_CONFIRMACAO)
        # pending_groups retornado na resposta
        self.assertEqual(len(r.data['pending_groups']), 1)
        self.assertEqual(r.data['pending_groups'][0]['id'], str(self.group.pk))
