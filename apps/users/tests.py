"""
Testes críticos do sistema de autenticação M2F.
Execute com: python manage.py test apps.users --verbosity=2
"""
import hashlib
import time

import pyotp
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import TrustedDevice, TwoFactorConfig, PasswordResetCode, generate_backup_codes
from .tokens import TwoFAPendingToken

User = get_user_model()

# Chave de teste estável — usada via @override_settings para isolar os testes
# do ambiente (funciona mesmo sem TOTP_ENCRYPTION_KEY no .env).
# Esta chave é pública (estava hardcoded no settings.py), mas é segura para testes.
_TEST_ENCRYPTION_KEY = 'YNqvfjrYdzvwqJQQiHQCV_-2eeWNfya4UAHsxiNdNwU='


def _make_user(email='user@test.com', password='TestPass123!'):
    return User.objects.create_user(
        username=email, email=email, password=password,
    )


@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
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

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class PendingTokenScopeTest(TestCase):
    """
    Verifica que um TwoFAPendingToken (type='2fa_pending') NÃO dá acesso
    a endpoints protegidos que exigem um AccessToken (type='access').
    """

    def setUp(self):
        cache.clear()
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

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class TwoFactorChallengeTest(TestCase):

    def setUp(self):
        cache.clear()
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

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class TOTPReplayTest(TestCase):

    def setUp(self):
        cache.clear()
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

        r1 = self.client.post('/api/auth/2fa/challenge/', {
            'pending_token': pending,
            'code': code,
            'trust_device': False,
        }, format='json')
        self.assertEqual(r1.status_code, 200, msg=f"Primeira submissão falhou: {r1.data}")

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

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class BackupCodeSingleUseTest(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _make_user('backup@test.com')
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

        self.config.refresh_from_db()
        consumed_hash = hashlib.sha256(code.encode()).hexdigest()
        self.assertNotIn(consumed_hash, self.config.backup_codes,
                         msg="Hash do backup code não foi removido do banco após uso.")


# ---------------------------------------------------------------------------
# 5. Login com trusted device pula challenge
# ---------------------------------------------------------------------------

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class TrustedDeviceSkipsChallenge(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _make_user('trusted@test.com')
        self.config = _make_2fa(self.user)
        self.client = APIClient()

    def test_trusted_device_token_bypasses_2fa(self):
        """Login com trusted_device_token válido retorna tokens diretamente (sem 2FA)."""
        import secrets as sec
        from datetime import timedelta
        from django.utils import timezone
        td_token = sec.token_hex(32)
        td_hash = hashlib.sha256(td_token.encode()).hexdigest()
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


# ---------------------------------------------------------------------------
# 6. Rate limit: 5 falhas → 6ª bloqueada mesmo com código correto
# ---------------------------------------------------------------------------

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class TOTPRateLimitTest(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _make_user('ratelimit@test.com')
        self.config = _make_2fa(self.user)
        self.client = APIClient()

    def _pending_token(self) -> str:
        token = TwoFAPendingToken()
        token['user_id'] = self.user.pk
        return str(token)

    def test_rate_limit_blocks_after_5_failures(self):
        """5 tentativas erradas → 6ª retorna bloqueio, mesmo com código correto."""
        correct_code = pyotp.TOTP(self.config.secret).now()
        # Garante que wrong_code não é acidentalmente correto
        wrong_code = '000000' if correct_code != '000000' else '111111'

        for _ in range(5):
            self.client.post('/api/auth/2fa/challenge/', {
                'pending_token': self._pending_token(),
                'code': wrong_code,
                'trust_device': False,
            }, format='json')

        # 6ª tentativa com código CORRETO — deve ser bloqueada
        r = self.client.post('/api/auth/2fa/challenge/', {
            'pending_token': self._pending_token(),
            'code': correct_code,
            'trust_device': False,
        }, format='json')

        self.assertNotEqual(
            r.status_code, 200,
            msg=f"FALHA: rate limit não bloqueou após 5 tentativas incorretas. "
                f"Status: {r.status_code}, body: {r.data}"
        )
        self.assertIn(
            'tentativa', str(r.data).lower(),
            msg=f"Resposta de bloqueio não menciona tentativas: {r.data}"
        )


# ---------------------------------------------------------------------------
# 7. Criptografia: secret não é texto plano no banco
# ---------------------------------------------------------------------------

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class TOTPEncryptionAtRestTest(TestCase):

    def setUp(self):
        cache.clear()

    def test_secret_is_encrypted_in_database(self):
        """Secret TOTP deve estar criptografado (Fernet) no banco — não em texto plano."""
        user = _make_user('encrypt@test.com')
        secret = pyotp.random_base32()
        config = TwoFactorConfig.objects.create(
            user=user, secret=secret, is_active=True, backup_codes=[],
        )

        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT tfa_secret FROM configs_2fa WHERE tfa_id = %s', [config.pk]
            )
            raw_secret = cursor.fetchone()[0]

        self.assertNotEqual(
            raw_secret, secret,
            msg=f"FALHA DE SEGURANÇA: secret TOTP em texto plano no banco! "
                f"Valor raw: {raw_secret!r}"
        )
        self.assertTrue(
            raw_secret.startswith('gAAAAA'),
            msg=f"Valor no banco não parece ser token Fernet válido: {raw_secret!r}"
        )


# ---------------------------------------------------------------------------
# 8. Reset de senha revoga dispositivos confiados
# ---------------------------------------------------------------------------

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class ResetPasswordRevokesTrustedDeviceTest(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _make_user('resetrevoke@test.com')
        self.config = _make_2fa(self.user)
        self.client = APIClient()

    def test_password_reset_revokes_trusted_devices(self):
        """Reset de senha deve revogar todos os trusted devices."""
        import secrets as sec
        from datetime import timedelta
        from django.utils import timezone

        td_token = sec.token_hex(32)
        TrustedDevice.objects.create(
            user=self.user,
            token_hash=hashlib.sha256(td_token.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(days=30),
        )

        reset_code = PasswordResetCode.generate(self.user)
        r = self.client.post('/api/auth/password/reset/', {
            'email': self.user.email,
            'code': reset_code,
            'password': 'NewStrongPass456!',
        }, format='json')
        self.assertEqual(r.status_code, 200, msg=f"Reset de senha falhou: {r.data}")

        self.assertEqual(
            TrustedDevice.objects.filter(user=self.user).count(), 0,
            msg="FALHA: trusted device não foi revogado após reset de senha!"
        )

        # Login com trusted_device_token antigo deve exigir 2FA
        r2 = self.client.post('/api/auth/login/', {
            'email': self.user.email,
            'password': 'NewStrongPass456!',
            'trusted_device_token': td_token,
        }, format='json')
        self.assertTrue(
            r2.data.get('requires_2fa', False),
            msg=f"FALHA: token revogado ainda pulou o challenge 2FA! Resposta: {r2.data}"
        )


# ---------------------------------------------------------------------------
# 9. TrustedDeviceListView / TrustedDeviceDeleteView
# ---------------------------------------------------------------------------

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class TrustedDeviceManagementTest(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _make_user('devices@test.com')
        self.config = _make_2fa(self.user)
        self.client = APIClient()
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')

    def _create_device(self, label='TestBrowser'):
        import secrets as sec
        from datetime import timedelta
        from django.utils import timezone
        return TrustedDevice.objects.create(
            user=self.user,
            token_hash=hashlib.sha256(sec.token_hex(32).encode()).hexdigest(),
            user_agent=label,
            expires_at=timezone.now() + timedelta(days=30),
        )

    def test_list_trusted_devices(self):
        d1 = self._create_device('Chrome')
        d2 = self._create_device('Firefox')

        r = self.client.get('/api/auth/2fa/trusted-devices/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 2)
        ids = {item['id'] for item in r.data}
        self.assertIn(d1.id, ids)
        self.assertIn(d2.id, ids)

    def test_delete_specific_device_leaves_others(self):
        d1 = self._create_device('Chrome')
        d2 = self._create_device('Firefox')

        r = self.client.delete(f'/api/auth/2fa/trusted-devices/{d1.id}/')
        self.assertEqual(r.status_code, 204, msg=f"DELETE falhou: {r.data if hasattr(r, 'data') else ''}")

        self.assertFalse(
            TrustedDevice.objects.filter(pk=d1.id).exists(),
            msg="d1 ainda existe após DELETE"
        )
        self.assertTrue(
            TrustedDevice.objects.filter(pk=d2.id).exists(),
            msg="d2 foi removido indevidamente"
        )

    def test_delete_other_users_device_returns_404(self):
        import secrets as sec
        from datetime import timedelta
        from django.utils import timezone
        other_user = _make_user('other@test.com')
        td = TrustedDevice.objects.create(
            user=other_user,
            token_hash=hashlib.sha256(sec.token_hex(32).encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        r = self.client.delete(f'/api/auth/2fa/trusted-devices/{td.id}/')
        self.assertEqual(r.status_code, 404,
                         msg="DELETE de device de outro usuário não retornou 404")


# ---------------------------------------------------------------------------
# 10. Blacklist de tokens ao desativar 2FA
# ---------------------------------------------------------------------------

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class BlacklistOnTwoFactorDisableTest(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _make_user('blacklist@test.com')
        self.client = APIClient()

    def test_disable_2fa_blacklists_refresh_tokens(self):
        """Desativar 2FA invalida todos os refresh tokens existentes."""
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

        config = _make_2fa(self.user)

        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')

        r = self.client.post('/api/auth/2fa/disable/', {
            'password': 'TestPass123!',
            'code': pyotp.TOTP(config.secret).now(),
        }, format='json')
        self.assertEqual(r.status_code, 200, msg=f"Falha ao desativar 2FA: {r.data}")

        jti = refresh.payload['jti']
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=jti).exists(),
            msg="FALHA: refresh token não foi adicionado ao blacklist após desativar 2FA!"
        )


# ---------------------------------------------------------------------------
# 11. Race condition anti-replay — concorrência real com threading
# ---------------------------------------------------------------------------

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class TOTPReplayConcurrentTest(TransactionTestCase):
    """
    Testa anti-replay com concorrência real via threading.

    NOTA sobre SQLite: o SQLite serializa writes a nível de lock de arquivo
    (uma thread escreve por vez). O teste passa corretamente porque nosso
    exclude() faz o segundo UPDATE retornar 0 rows quando o counter já foi
    aceito — mas a serialização do SQLite garante que o primeiro UPDATE
    termine antes do segundo começar. Em PostgreSQL, ambos os UPDATEs podem
    ocorrer verdadeiramente em paralelo, e o exclude() é o único mecanismo
    que impede o double-accept (sem lock explícito de linha, pois o UPDATE
    WHERE é atômico em nível de row no PG). O resultado final (apenas um
    True) é o mesmo em ambos os bancos.

    Use `test_stale_object_replay_blocked_by_atomic_update` para verificar
    o exclude() diretamente, isolado de qualquer serialização de banco.
    """

    def setUp(self):
        cache.clear()
        self.user = _make_user('concurrent@test.com')
        self.config = _make_2fa(self.user)

    def test_concurrent_threads_only_one_passes(self):
        """Duas threads simultâneas com o mesmo código: exatamente uma retorna True."""
        import threading
        from django.db import connection as _conn

        code = pyotp.TOTP(self.config.secret).now()
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def attempt():
            # Cada thread carrega o objeto fresh do banco — simula requests independentes
            config = TwoFactorConfig.objects.get(pk=self.config.pk)
            barrier.wait()  # sincroniza: ambas as threads partem ao mesmo tempo
            result = config.verify_totp_or_backup(code)
            with lock:
                results.append(result)
            # Fecha a conexão da thread para não vazar handles
            _conn.close()

        t1 = threading.Thread(target=attempt)
        t2 = threading.Thread(target=attempt)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        self.assertEqual(len(results), 2, "Ambas as threads devem terminar dentro do timeout")
        self.assertEqual(
            results.count(True), 1,
            f"FALHA: {results.count(True)} thread(s) retornaram True. "
            f"Esperado: exatamente 1. Results: {results}"
        )

    def test_stale_object_replay_blocked_by_atomic_update(self):
        """
        Isola o mecanismo do exclude(): um objeto stale em memória
        (last_otp_counter desatualizado) não consegue aceitar um código já usado.
        Este teste verifica o exclude() independente de qualquer banco.
        """
        code = pyotp.TOTP(self.config.secret).now()

        result1 = self.config.verify_totp_or_backup(code)
        self.assertTrue(result1, "Primeira verificação deve passar")

        # Carrega objeto stale simulando leitura antes do update do 1º request (TOCTOU)
        config_stale = TwoFactorConfig.objects.get(pk=self.config.pk)
        config_stale.last_otp_counter = -1

        result2 = config_stale.verify_totp_or_backup(code)
        self.assertFalse(
            result2,
            "FALHA: exclude() não bloqueou objeto com last_otp_counter stale!"
        )


# ---------------------------------------------------------------------------
# 12. Rotação de chave de criptografia — teste direto da lógica da migration
# ---------------------------------------------------------------------------

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class KeyRotationMigrationTest(TestCase):
    """Testa rotate_key_forward da migration 0009 diretamente, sem passar pelo migrate."""

    def setUp(self):
        cache.clear()

    def test_rotate_key_forward_re_encrypts_correctly(self):
        """
        Grava secret criptografado com OLD_KEY no banco via SQL, chama
        rotate_key_forward diretamente e confirma que o resultado descriptografa
        com a nova chave.
        """
        import importlib
        import os
        from unittest.mock import MagicMock, patch
        from cryptography.fernet import Fernet
        from django.db import connection

        # Importa o módulo de migration via importlib (nome começa com dígito)
        migration_mod = importlib.import_module(
            'apps.users.migrations.0009_rotate_totp_encryption_key'
        )

        OLD_KEY = 'YNqvfjrYdzvwqJQQiHQCV_-2eeWNfya4UAHsxiNdNwU='
        NEW_KEY = Fernet.generate_key().decode()

        plaintext_secret = pyotp.random_base32()
        old_fernet = Fernet(OLD_KEY.encode())
        encrypted_with_old = old_fernet.encrypt(plaintext_secret.encode()).decode()

        # Cria o config com placeholder (será sobrescrito via SQL)
        user = _make_user('keyrotation@test.com')
        config = TwoFactorConfig.objects.create(
            user=user, secret=pyotp.random_base32(), is_active=True, backup_codes=[],
        )

        # Sobrescreve o secret com o valor criptografado pela OLD_KEY
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE configs_2fa SET tfa_secret = %s WHERE tfa_id = %s',
                [encrypted_with_old, config.pk],
            )

        # Confirma que o valor foi gravado corretamente
        with connection.cursor() as cursor:
            cursor.execute('SELECT tfa_secret FROM configs_2fa WHERE tfa_id = %s', [config.pk])
            raw_before = cursor.fetchone()[0]
        self.assertEqual(raw_before, encrypted_with_old, 'Setup: valor não foi gravado via SQL')

        # Mock do schema_editor apontando para a conexão real de teste
        mock_editor = MagicMock()
        mock_editor.connection = connection

        # Executa a lógica de rotação com TOTP_OLD_ENCRYPTION_KEY via env e NEW_KEY via settings
        with patch.dict(os.environ, {'TOTP_OLD_ENCRYPTION_KEY': OLD_KEY}):
            with self.settings(TOTP_ENCRYPTION_KEY=NEW_KEY):
                migration_mod.rotate_key_forward(None, mock_editor)

        # Lê o valor rotacionado
        with connection.cursor() as cursor:
            cursor.execute('SELECT tfa_secret FROM configs_2fa WHERE tfa_id = %s', [config.pk])
            raw_after = cursor.fetchone()[0]

        self.assertNotEqual(raw_after, encrypted_with_old, 'Valor não foi rotacionado no banco')

        # Descriptografa com a nova chave e confirma equivalência com o plaintext original
        new_fernet = Fernet(NEW_KEY.encode())
        decrypted = new_fernet.decrypt(raw_after.encode()).decode()
        self.assertEqual(
            decrypted, plaintext_secret,
            f'Plaintext diverge após rotação! Esperado: {plaintext_secret!r}, obtido: {decrypted!r}'
        )


# ---------------------------------------------------------------------------
# 13. Blacklist de tokens ao ATIVAR 2FA
# ---------------------------------------------------------------------------

@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class BlacklistOnTwoFactorActivateTest(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _make_user('blacklist_activate@test.com')
        self.client = APIClient()

    def test_activate_2fa_blacklists_refresh_tokens(self):
        """Ativar 2FA invalida todos os refresh tokens existentes."""
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

        # Emite refresh token ANTES de ativar 2FA
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')

        # Inicia o setup (GET retorna secret + URI)
        r_setup = self.client.get('/api/auth/2fa/setup/')
        self.assertEqual(r_setup.status_code, 200, f'Setup falhou: {r_setup.data}')
        secret = r_setup.data['secret']

        # Confirma com código TOTP válido — ativa 2FA e blacklista tokens
        code = pyotp.TOTP(secret).now()
        r_confirm = self.client.post('/api/auth/2fa/setup/confirm/', {'code': code}, format='json')
        self.assertEqual(r_confirm.status_code, 200, f'Confirm falhou: {r_confirm.data}')

        # Verifica que o refresh token emitido ANTES da ativação está no blacklist
        jti = refresh.payload['jti']
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=jti).exists(),
            'FALHA: refresh token não foi blacklistado após ativar 2FA!'
        )
