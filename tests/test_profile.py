"""
Edição de perfil (PATCH /api/auth/me/).
Edita nome + preferências de notificação; nunca escala plan/is_staff/phone_verified.
"""
from django.contrib.auth import get_user_model

from .helpers import SecurityTestCase

User = get_user_model()
ME = '/api/auth/me/'


class ProfileEditTest(SecurityTestCase):
    def test_update_name_and_prefs(self):
        tok, uid = self.register('victim')
        r = self.api(tok).patch(ME, {
            'name': 'Maria Silva Souza',
            'notif_cobracas': False,
            'notif_confirmacoes': True,
            'notif_lembretes': False,
        }, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['name'], 'Maria Silva Souza')
        self.assertFalse(r.data['notif_cobracas'])
        u = User.objects.get(pk=uid)
        self.assertEqual(u.first_name, 'Maria')
        self.assertEqual(u.last_name, 'Silva Souza')

    def test_cannot_escalate_via_profile(self):
        tok, uid = self.register('victim')
        self.api(tok).patch(ME, {
            'name': 'X', 'plan': 'pro', 'is_staff': True, 'is_superuser': True, 'phone_verified': True,
        }, format='json')
        u = User.objects.get(pk=uid)
        self.assertEqual(u.plan, 'free')
        self.assertFalse(u.is_staff)
        self.assertFalse(u.is_superuser)
        self.assertFalse(u.phone_verified)

    def test_empty_name_rejected(self):
        tok, _ = self.register('victim')
        r = self.api(tok).patch(ME, {'name': '   '}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_requires_auth(self):
        self.assertEqual(self.api().patch(ME, {'name': 'X'}, format='json').status_code, 401)
