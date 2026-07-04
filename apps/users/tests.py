"""
Testes críticos do sistema de autenticação M2F.
Execute com: python manage.py test apps.users --verbosity=2
"""
import hashlib
import time

import pyotp
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import TrustedDevice, TwoFactorConfig, generate_backup_codes
from .tokens import TwoFAPendingToken

User = get_user_model()

# Chave de teste estável para criptografia (apenas em testes)
_TEST_ENCRYPTION_KEY = 'YNqvfjrYdzvwqJQQiHQCV_-2eeWNfya4UAHsxiNdNwU='


def _make_user(email='user@test.com', password='TestPass123!'):
    return User.objects.create_user(
        username=email, email=email, password=password,
    )


def _make_2fa(user) -> TwoFactorConfig:
    """Cria TwoFactorConfig ativo com secret TOTP."""
    secret = pyotp.random_base32()
    config = TwoFactorConfig.objects.create(
        user=user,
        secret=secret,
        is_active=True,
        backup_codes=[hashlib.sha256(c.encode()).hexdigest() for c in generate_backup_codes(8)],
    )
    return config


# ---------------------------------------------------------------------------
# 1. Escopo do pending_token
# ---------------------------------------------------------------------------

class PendingTokenScopeTest(TestCase):
    """
    Verifica que um TwoFAPendingToken (type='2fa_pending') NÃO dá acesso
    a endpoints protegidos que exigem um AccessToken (type='access').
    """

    def setUp(self):
        self.user = _make_user()
        self.client = APIClient()

    def test_pending_token_rejected_on_me_endpoint(self):
        """pending_token em GET /api/auth/me/ deve retornar 401."""
        token = TwoFAPendingToken()
        token['user_id'] = self.user.pk
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(token)}')
        response = self.client.get('/api/auth/me/')
        self.assertEqual(
            response.status_code, 401,
            msg=f"FALHA DE SEGURANÇA: pending_token foi aceito em rota protegida! "
                f"Status retornado: {response.status_code}, body: {response.data}"
        )


# ---------------------------------------------------------------------------
# 2. Challenge com código TOTP correto
# ---------------------------------------------------------------------------

class TwoFactorChallengeTest(TestCase):

    def setUp(self):
        self.user = _make_user()
        self.config = _make_2fa(self.user)
        self.client = APIClient()

    def _pending_token(self) -> str:
        token = TwoFAPendingToken()
        token['user_id'] = self.user.pk
        return str(token)

    def test_challenge_with_valid_totp_returns_tokens(self):
        """Challenge com código TOTP correto retorna access + refresh + user."""
        code = pyotp.TOTP(self.config.secret).now()
        response = self.client.post('/api/auth/2fa/challenge/', {
            'pending_token': self._pending_token(),
            'code': code,
            'trust_device': False,
        }, format='json')
        self.assertEqual(response.status_code, 200,
                         msg=f"Esperado 200, recebido {response.status_code}: {response.data}")
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertIn('user', response.data)


# ---------------------------------------------------------------------------
# 3. Replay do mesmo código TOTP
# ---------------------------------------------------------------------------

class TOTPReplayTest(TestCase):

    def setUp(self):
        self.user = _make_user('replay@test.com')
        self.config = _make_2fa(self.user)
        self.client = APIClient()

    def _pending_token(self) -> str:
        token = TwoFAPendingToken()
        token['user_id'] = self.user.pk
        return str(token)

    def test_same_totp_code_rejected_on_second_use(self):
        """O mesmo código TOTP deve ser rejeitado na segunda tentativa (replay)."""
        code = pyotp.TOTP(self.config.secret).now()
        pending = self._pending_token()

        # Primeira vez: deve funcionar
        r1 = self.client.post('/api/auth/2fa/challenge/', {
            'pending_token': pending,
            'code': code,
            'trust_device': False,
        }, format='json')
        self.assertEqual(r1.status_code, 200, msg=f"Primeira submissão falhou: {r1.data}")

        # Segunda vez com o mesmo código: deve ser rejeitado
        pending2 = self._pending_token()
        r2 = self.client.post('/api/auth/2fa/challenge/', {
            'pending_token': pending2,
            'code': code,
            'trust_device': False,
        }, format='json')
        self.assertNotEqual(
            r2.status_code, 200,
            msg=f"FALHA DE SEGURANÇA: replay do código TOTP foi aceito! "
                f"Status: {r2.status_code}, body: {r2.data}"
        )


# ---------------------------------------------------------------------------
# 4. Backup code de uso único
# ---------------------------------------------------------------------------

class BackupCodeSingleUseTest(TestCase):

    def setUp(self):
        self.user = _make_user('backup@test.com')
        # Cria 2FA com backup codes conhecidos
        self.raw_codes = generate_backup_codes(8)
        self.config = TwoFactorConfig.objects.create(
            user=self.user,
            secret=pyotp.random_base32(),
            is_active=True,
            backup_codes=[hashlib.sha256(c.encode()).hexdigest() for c in self.raw_codes],
        )
        self.client = APIClient()

    def _pending_token(self) -> str:
        token = TwoFAPendingToken()
        token['user_id'] = self.user.pk
        return str(token)

    def test_backup_code_single_use(self):
        """Backup code deve funcionar na primeira vez e ser rejeitado na segunda."""
        code = self.raw_codes[0]

        r1 = self.client.post('/api/auth/2fa/challenge/', {
            'pending_token': self._pending_token(),
            'code': code,
            'trust_device': False,
        }, format='json')
        self.assertEqual(r1.status_code, 200,
                         msg=f"Backup code legítimo foi rejeitado: {r1.data}")

        # Segundo uso — deve ser rejeitado (código consumido)
        r2 = self.client.post('/api/auth/2fa/challenge/', {
            'pending_token': self._pending_token(),
            'code': code,
            'trust_device': False,
        }, format='json')
        self.assertNotEqual(
            r2.status_code, 200,
            msg=f"FALHA DE SEGURANÇA: backup code foi aceito duas vezes! "
                f"Status: {r2.status_code}, body: {r2.data}"
        )

        # Verifica que o hash foi removido do banco
        self.config.refresh_from_db()
        consumed_hash = hashlib.sha256(code.encode()).hexdigest()
        self.assertNotIn(consumed_hash, self.config.backup_codes,
                         msg="Hash do backup code não foi removido do banco após uso.")


# ---------------------------------------------------------------------------
# 5. Login com trusted device pula challenge
# ---------------------------------------------------------------------------

class TrustedDeviceSkipsChallenge(TestCase):

    def setUp(self):
        self.user = _make_user('trusted@test.com')
        self.config = _make_2fa(self.user)
        self.client = APIClient()

    def test_trusted_device_token_bypasses_2fa(self):
        """Login com trusted_device_token válido retorna tokens diretamente (sem 2FA)."""
        import secrets as sec
        td_token = sec.token_hex(32)
        td_hash = hashlib.sha256(td_token.encode()).hexdigest()
        from django.utils import timezone
        from datetime import timedelta
        TrustedDevice.objects.create(
            user=self.user,
            token_hash=td_hash,
            expires_at=timezone.now() + timedelta(days=30),
        )

        response = self.client.post('/api/auth/login/', {
            'email': 'trusted@test.com',
            'password': 'TestPass123!',
            'trusted_device_token': td_token,
        }, format='json')

        self.assertEqual(response.status_code, 200,
                         msg=f"Login com trusted device falhou: {response.data}")
        self.assertNotIn('requires_2fa', response.data,
                         msg="Trusted device NÃO pulou o desafio 2FA!")
        self.assertIn('access', response.data,
                      msg="Resposta sem token de acesso")
