"""
Bloco 3 — PATCH que muda o escopo do recurso.
Tentativas de mover um recurso para fora do alcance de autorização via EDIÇÃO
(não só criação): trocar group_id, debtor_id, paid_by_id, created_by, etc.
"""
from django.contrib.auth import get_user_model

from apps.groups.models import Group
from .helpers import SecurityTestCase

User = get_user_model()


class DebtScopeOnEditTest(SecurityTestCase):
    """A edição de despesa não pode mover o recurso de escopo (grupo)."""

    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)  # membro/credor legítimo

    def test_patch_debt_cannot_change_group(self):
        before = self.vic.get(f'/api/despesas/{self.s.debt_id}/').data['group_id']
        r = self.vic.patch(f'/api/despesas/{self.s.debt_id}/', {
            'description': 'Renomeada',
            'group_id': self.s.atk_group_id,   # tentativa de mover de grupo — deve ser ignorada
        }, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(str(r.data['group_id']), str(before))  # grupo não mudou

    def test_put_debt_not_allowed(self):
        r = self.vic.put(f'/api/despesas/{self.s.debt_id}/',
                         {'description': 'x'}, format='json')
        self.assertEqual(r.status_code, 405)

    def test_patch_installment_not_allowed(self):
        r = self.vic.patch(f'/api/parcelas/{self.s.parcela_byt}/',
                           {'debtor_id': self.s.atk_id}, format='json')
        self.assertEqual(r.status_code, 405)


class MePatchScopeTest(SecurityTestCase):
    """PATCH /me/ só edita campos próprios permitidos; nunca id/email/plan/staff."""

    def test_cannot_change_identity_fields(self):
        vic_t, vic_id = self.register('victim')
        before = User.objects.get(pk=vic_id)
        r = self.api(vic_t).patch('/api/auth/me/', {
            'id': 999999,
            'email': 'hacked@example.invalid',
            'plan': 'pro',
            'is_staff': True,
            'is_superuser': True,
            'phone': '+5599911112222',
            'phone_verified': True,
            'avatar_url': 'https://x.invalid/a.png',  # este é permitido
        }, format='json')
        self.assertEqual(r.status_code, 200)
        after = User.objects.get(pk=vic_id)
        self.assertEqual(after.pk, before.pk)
        self.assertEqual(after.email, before.email)
        self.assertEqual(after.plan, 'free')
        self.assertFalse(after.is_staff)
        self.assertFalse(after.is_superuser)
        self.assertFalse(after.phone_verified)
        self.assertEqual(after.avatar_url, 'https://x.invalid/a.png')  # confirma que o PATCH funcionou


class GroupPatchScopeTest(SecurityTestCase):
    """PATCH grupo: admin edita nome; ninguém reatribui created_by; não-admin/outsider = 404."""

    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()

    def test_admin_cannot_reassign_created_by_or_id(self):
        before = Group.objects.get(pk=self.s.group_id)
        r = self.api(self.s.vic_t).patch(f'/api/grupos/{self.s.group_id}/', {
            'name': 'Renomeado',
            'created_by': self.s.atk_id,   # tentativa de reatribuir dono
            'id': '11111111-1111-4111-8111-111111111111',
            'archived': True,
        }, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        after = Group.objects.get(pk=self.s.group_id)
        self.assertEqual(str(after.pk), str(before.pk))              # id imutável
        self.assertEqual(after.created_by_id, before.created_by_id)  # dono imutável
        self.assertEqual(after.name, 'Renomeado')                    # campo permitido mudou

    def test_non_admin_member_cannot_patch_group(self):
        before = Group.objects.get(pk=self.s.group_id).name
        r = self.api(self.s.byt_t).patch(f'/api/grupos/{self.s.group_id}/',
                                        {'name': 'Hackeado'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Group.objects.get(pk=self.s.group_id).name, before)

    def test_outsider_cannot_patch_group(self):
        r = self.api(self.s.atk_t).patch(f'/api/grupos/{self.s.group_id}/',
                                        {'name': 'Hackeado'}, format='json')
        self.assertEqual(r.status_code, 404)


class ConfirmPaymentBodyInjectionTest(SecurityTestCase):
    """confirmar/ ignora campos de relacionamento no corpo — não muda escopo da parcela."""

    def test_confirm_ignores_injected_relations(self):
        s = self.build_scenario()
        # devedor declara pagamento -> awaiting
        self.api(s.byt_t).post(f'/api/parcelas/{s.parcela_byt}/comprovante/', {}, format='json')
        # credor confirma, tentando injetar troca de escopo no corpo
        r = self.api(s.vic_t).patch(f'/api/parcelas/{s.parcela_byt}/confirmar/', {
            'debtor_id': s.atk_id,
            'paid_by_id': s.atk_id,
            'group_id': s.atk_group_id,
            'amount_cents': 1,
            'status': 'paid',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.content)

        # recarrega o detalhe e confirma que nada de escopo mudou
        detail = self.api(s.vic_t).get(f'/api/despesas/{s.debt_id}/').data
        self.assertEqual(str(detail['group_id']), str(s.group_id))
        self.assertEqual(str(detail['paid_by']['id']), str(s.vic_id))
        parc = {str(p['debtor']['id']): p for p in detail['parcelas']}
        self.assertIn(str(s.byt_id), parc)                       # devedor original intacto
        self.assertEqual(parc[str(s.byt_id)]['status'], 'paid')  # a única mudança: status
        self.assertEqual(parc[str(s.byt_id)]['amount_cents'], 5000)  # valor não foi adulterado


class CreateBodyInjectionRegressionTest(SecurityTestCase):
    """Regressão: paid_by_id/created_by no corpo da criação são ignorados (credor = request.user)."""

    def test_paid_by_id_in_body_is_ignored(self):
        s = self.build_scenario()
        # bystander cria dívida tentando gravar victim como credor
        r = self.api(s.byt_t).post('/api/despesas/', {
            'grupo_id': s.group_id,
            'description': 'Forjada',
            'total_amount_cents': 3000,
            'split_type': 'custom',
            'paid_by_id': s.vic_id,       # tentativa de forjar o credor
            'created_by': s.vic_id,
            'parcelas': [{'debtor_id': int(s.mb3_id), 'amount_cents': 3000}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(str(r.data['paid_by']['id']), str(s.byt_id))  # credor = quem criou
