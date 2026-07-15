"""Endpoint de health — alvo do monitor de uptime. Público e sem auth."""
from .helpers import SecurityTestCase


class HealthTest(SecurityTestCase):
    def test_health_is_public_and_ok(self):
        r = self.api().get('/health/')  # sem token
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['status'], 'ok')
        self.assertTrue(body['database'])
