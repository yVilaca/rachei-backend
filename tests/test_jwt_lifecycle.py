"""
Bloco 1 — Ciclo de vida do JWT.
Confirma que o backend não aceita tokens forjados, adulterados, expirados,
de tipo errado, nem refresh tokens reusados após rotação/blacklist.

Todos os tokens legítimos são obtidos via /login real.
"""
import base64
import json
from datetime import timedelta

import jwt
import pyotp
from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken

from .helpers import SecurityTestCase, TEST_ENCRYPTION_KEY

ME = '/api/auth/me/'
REFRESH = '/api/auth/refresh/'
REFRESH_COOKIE = 'rachei_refresh'


def _b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b'=').decode()


def _pad(s: str) -> str:
    return s + '=' * (-len(s) % 4)


class TokenForgeryTest(SecurityTestCase):
    """Tokens forjados/adulterados/expirados devem ser rejeitados (401)."""

    def setUp(self):
        super().setUp()
        self.register('victim')
        r = self.login('victim')
        self.assertEqual(r.status_code, 200, r.content)
        self.access = r.data['access']
        self.user_id = r.data['user']['id']
        self.refresh_value = r.cookies[REFRESH_COOKIE].value

    def test_sanity_valid_access_works(self):
        # garante que os negativos abaixo não passam por setup quebrado
        self.assertEqual(self.api(self.access).get(ME).status_code, 200)

    def test_tampered_payload_old_signature_rejected(self):
        h, p, s = self.access.split('.')
        payload = json.loads(base64.urlsafe_b64decode(_pad(p)))
        payload['user_id'] = 999999  # tenta virar outro usuário
        forged = f'{h}.{_b64(payload)}.{s}'  # assinatura antiga não bate
        self.assertEqual(self.api(forged).get(ME).status_code, 401)

    def test_alg_none_rejected(self):
        header = {'alg': 'none', 'typ': 'JWT'}
        payload = {
            'token_type': 'access', 'jti': 'forged', 'user_id': self.user_id,
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp()),
        }
        none_token = f'{_b64(header)}.{_b64(payload)}.'
        self.assertEqual(self.api(none_token).get(ME).status_code, 401)

    def test_wrong_signing_key_rejected(self):
        payload = {
            'token_type': 'access', 'jti': 'x', 'user_id': self.user_id,
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp()),
            'iat': int(timezone.now().timestamp()),
        }
        bad = jwt.encode(payload, 'chave-totalmente-errada', algorithm='HS256')
        self.assertEqual(self.api(bad).get(ME).status_code, 401)

    def test_hs_signed_with_guessed_default_secret_rejected(self):
        # Atacante chuta o SECRET_KEY padrão inseguro do Django — deve falhar (401)
        payload = {
            'token_type': 'access', 'jti': 'x', 'user_id': self.user_id,
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp()),
        }
        bad = jwt.encode(payload, 'django-insecure-change-me', algorithm='HS256')
        self.assertEqual(self.api(bad).get(ME).status_code, 401)

    def test_expired_access_rejected(self):
        t = AccessToken()
        t[api_settings.USER_ID_CLAIM] = self.user_id
        t.set_exp(from_time=timezone.now() - timedelta(hours=2), lifetime=timedelta(hours=1))
        expired = str(t)  # assinado com a secret real, porém expirado
        self.assertEqual(self.api(expired).get(ME).status_code, 401)

    def test_refresh_used_as_access_rejected(self):
        # o refresh real (do cookie) não pode autenticar rota protegida
        self.assertEqual(self.api(self.refresh_value).get(ME).status_code, 401)


class RefreshRotationTest(SecurityTestCase):
    """Refresh rotacionado/blacklistado não pode ser reutilizado."""

    def test_reused_refresh_after_rotation_rejected(self):
        self.register('victim')
        r = self.login('victim')
        r1 = r.cookies[REFRESH_COOKIE].value

        # primeiro uso: rotaciona (blacklista r1, emite r2)
        c1 = self.api()
        c1.cookies[REFRESH_COOKIE] = r1
        first = c1.post(REFRESH, {}, format='json')
        self.assertEqual(first.status_code, 200, first.content)

        # segundo uso do MESMO r1: deve falhar (401)
        c2 = self.api()
        c2.cookies[REFRESH_COOKIE] = r1
        second = c2.post(REFRESH, {}, format='json')
        self.assertEqual(second.status_code, 401)


@override_settings(TOTP_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class TwoFactorToggleBlacklistTest(SecurityTestCase):
    """Ativar 2FA invalida todos os refresh tokens vigentes (blacklist)."""

    def test_activate_2fa_blacklists_existing_refresh(self):
        self.register('victim')
        r = self.login('victim')
        access = r.data['access']
        r1 = r.cookies[REFRESH_COOKIE].value

        # ativa 2FA de forma real: setup -> confirm com TOTP
        vic = self.api(access)
        setup = vic.get('/api/auth/2fa/setup/')
        self.assertEqual(setup.status_code, 200, setup.content)
        secret = setup.data['secret']
        code = pyotp.TOTP(secret).now()
        confirm = vic.post('/api/auth/2fa/setup/confirm/', {'code': code}, format='json')
        self.assertEqual(confirm.status_code, 200, confirm.content)

        # r1 (emitido antes do toggle) deve estar blacklistado
        c = self.api()
        c.cookies[REFRESH_COOKIE] = r1
        self.assertEqual(c.post(REFRESH, {}, format='json').status_code, 401)
