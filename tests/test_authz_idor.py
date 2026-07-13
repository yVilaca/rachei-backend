"""
Regressão de autorização em nível de objeto (IDOR / broken access control).
Cobre as categorias A–I da auditoria manual, agora como testes automatizados.

Modelo de ameaça: usuário mal-intencionado com TOKEN VÁLIDO tentando agir
sobre recursos que não lhe cabem.
"""
import hashlib
from datetime import timedelta

from django.utils import timezone

from apps.users.models import TrustedDevice
from .helpers import SecurityTestCase, PHONES


class CrossGroupReadTest(SecurityTestCase):
    """A — outsider nunca lê recurso de grupo alheio (404, nunca 403/200)."""

    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.atk = self.api(self.s.atk_t)

    def test_a1_get_group(self):
        self.assertEqual(self.atk.get(f'/api/grupos/{self.s.group_id}/').status_code, 404)

    def test_a2_get_group_debts(self):
        self.assertEqual(self.atk.get(f'/api/grupos/{self.s.group_id}/despesas/').status_code, 404)

    def test_a3_get_debt(self):
        self.assertEqual(self.atk.get(f'/api/despesas/{self.s.debt_id}/').status_code, 404)

    def test_a4_get_installment(self):
        self.assertEqual(self.atk.get(f'/api/parcelas/{self.s.parcela_byt}/').status_code, 404)

    def test_a5_get_members(self):
        self.assertEqual(self.atk.get(f'/api/grupos/{self.s.group_id}/membros/').status_code, 404)


class OutsiderFinancialActionTest(SecurityTestCase):
    """B — outsider não age financeiramente em parcela de grupo alheio (404)."""

    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.atk = self.api(self.s.atk_t)
        self.p = self.s.parcela_byt

    def test_b1_declare_payment(self):
        self.assertEqual(self.atk.post(f'/api/parcelas/{self.p}/comprovante/', {}, format='json').status_code, 404)

    def test_b2_confirm(self):
        self.assertEqual(self.atk.patch(f'/api/parcelas/{self.p}/confirmar/', {}, format='json').status_code, 404)

    def test_b3_reject(self):
        self.assertEqual(self.atk.post(f'/api/parcelas/{self.p}/rejeitar/', {}, format='json').status_code, 404)

    def test_b4_charge_link(self):
        self.assertEqual(self.atk.post(f'/api/parcelas/{self.p}/link-cobranca/', {}, format='json').status_code, 404)


class InsufficientRoleTest(SecurityTestCase):
    """C — membro sem o papel correto é bloqueado (400 credor/devedor, 403 admin)."""

    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.byt = self.api(self.s.byt_t)   # devedor / membro comum
        self.mb3 = self.api(self.s.mb3_t)   # membro comum
        self.vic = self.api(self.s.vic_t)   # credor / admin
        self.p = self.s.parcela_byt

    def test_c1_debtor_cannot_confirm(self):
        self.assertEqual(self.byt.patch(f'/api/parcelas/{self.p}/confirmar/', {}, format='json').status_code, 400)

    def test_c2_debtor_cannot_reject(self):
        self.assertEqual(self.byt.post(f'/api/parcelas/{self.p}/rejeitar/', {}, format='json').status_code, 400)

    def test_c3_debtor_cannot_generate_charge_link(self):
        self.assertEqual(self.byt.post(f'/api/parcelas/{self.p}/link-cobranca/', {}, format='json').status_code, 400)

    def test_c4_non_admin_cannot_add_member(self):
        r = self.byt.post(f'/api/grupos/{self.s.group_id}/membros/', {'phone': PHONES['outsider'], 'name': 'X'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_c5_non_admin_cannot_remove_member(self):
        r = self.mb3.delete(f'/api/grupos/{self.s.group_id}/membros/{self.s.byt_member_pk}/')
        self.assertEqual(r.status_code, 403)

    def test_c6_creditor_cannot_declare_debtors_payment(self):
        # declarar pagamento é exclusivo do devedor
        r = self.vic.post(f'/api/parcelas/{self.p}/comprovante/', {}, format='json')
        self.assertEqual(r.status_code, 400)


class OutOfGroupRelationOnCreateTest(SecurityTestCase):
    """D — não é possível criar dívida com devedor de fora do grupo."""

    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.atk = self.api(self.s.atk_t)

    def test_d1_debtor_outside_group_rejected(self):
        r = self.atk.post('/api/despesas/', {
            'grupo_id': self.s.atk_group_id,
            'description': 'x', 'total_amount_cents': 1000, 'split_type': 'custom',
            'parcelas': [{'debtor_id': int(self.s.vic_id), 'amount_cents': 1000}],
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_d2_create_in_foreign_group_rejected(self):
        r = self.atk.post('/api/despesas/', {
            'grupo_id': self.s.group_id,  # grupo da vítima
            'description': 'x', 'total_amount_cents': 1000, 'split_type': 'custom',
            'parcelas': [{'debtor_id': int(self.s.atk_id), 'amount_cents': 1000}],
        }, format='json')
        self.assertEqual(r.status_code, 404)


class MassAssignmentTest(SecurityTestCase):
    """E — PATCH /me/ não escala plan/is_staff/is_superuser."""

    def test_e1_no_privilege_escalation(self):
        from django.contrib.auth import get_user_model
        vic_t, vic_id = self.register('victim')
        r = self.api(vic_t).patch('/api/auth/me/', {
            'plan': 'pro', 'phone_verified': True,
            'is_staff': True, 'is_superuser': True,
            'avatar_url': 'https://x.invalid/a.png',
        }, format='json')
        self.assertEqual(r.status_code, 200)
        u = get_user_model().objects.get(pk=vic_id)
        self.assertEqual(u.plan, 'free')
        self.assertFalse(u.is_staff)
        self.assertFalse(u.is_superuser)
        self.assertFalse(u.phone_verified)


class UnauthenticatedTest(SecurityTestCase):
    """F — sem token / token inválido é 401."""

    def test_f1_dashboard_requires_auth(self):
        self.assertEqual(self.api().get('/api/dashboard/').status_code, 401)

    def test_f2_check_phone_requires_auth(self):
        self.assertEqual(self.api().get('/api/auth/check-phone/?phone=' + PHONES['victim']).status_code, 401)

    def test_f3_garbage_token_rejected(self):
        self.assertEqual(self.api('lixo.invalido.jwt').get('/api/grupos/').status_code, 401)


class ConfirmParticipationTest(SecurityTestCase):
    """G — não confirma participação em grupo alheio."""

    def test_g1_outsider_cannot_confirm_participation(self):
        s = self.build_scenario()
        r = self.api(s.atk_t).post(f'/api/grupos/{s.group_id}/confirmar/', {'aceitar': True}, format='json')
        self.assertEqual(r.status_code, 404)


class TrustedDeviceIdorTest(SecurityTestCase):
    """H — usuário não deleta trusted-device de outro (escopo por user)."""

    def test_h1_cannot_delete_other_users_device(self):
        atk_t, atk_id = self.register('attacker')
        vic_t, vic_id = self.register('victim')
        from django.contrib.auth import get_user_model
        attacker = get_user_model().objects.get(pk=atk_id)
        dev = TrustedDevice.objects.create(
            user=attacker,
            token_hash=hashlib.sha256(b'sectest').hexdigest(),
            user_agent='sectest',
            expires_at=timezone.now() + timedelta(days=30),
        )
        r = self.api(vic_t).delete(f'/api/auth/2fa/trusted-devices/{dev.pk}/')
        self.assertEqual(r.status_code, 404)
        self.assertTrue(TrustedDevice.objects.filter(pk=dev.pk).exists())
