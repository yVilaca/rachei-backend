"""
Enriquecimento da auditoria: login_ok e token_refresh acontecem em endpoints
onde request.user ainda é anônimo. O user é resolvido a partir do access token
e deve ser gravado no AuditLog (antes ficava nulo).
"""
from rest_framework.test import APIClient

from apps.users.models import AuditLog
from .helpers import SecurityTestCase

REFRESH = '/api/auth/refresh/'
REFRESH_COOKIE = 'rachei_refresh'


class AuditEnrichmentTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        _, self.uid = self.register('victim')

    def test_login_ok_registra_user(self):
        r = self.login('victim')
        self.assertEqual(r.status_code, 200, r.content)
        log = AuditLog.objects.filter(event=AuditLog.LOGIN_OK).latest('created_at')
        self.assertEqual(log.user_id, int(self.uid))

    def test_token_refresh_registra_user(self):
        r = self.login('victim')
        c = APIClient()
        c.cookies[REFRESH_COOKIE] = r.cookies[REFRESH_COOKIE].value
        rr = c.post(REFRESH, {}, format='json')
        self.assertEqual(rr.status_code, 200, rr.content)
        log = AuditLog.objects.filter(event=AuditLog.TOKEN_REFRESH).latest('created_at')
        self.assertEqual(log.user_id, int(self.uid))
