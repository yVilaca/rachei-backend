"""
Bloco 2 — Rate limiting / throttles.
Para cada throttle documentado, dispara além do limite e confirma o 429,
depois confirma que a janela reseta.

Nota sobre o reset: os throttles do DRF guardam os timestamps das requisições
no cache. Esvaziar o cache é equivalente ao deslizar da janela (as marcas
antigas expiram) — assim testamos o reset sem esperar o tempo real.
"""
from django.core.cache import cache

from .helpers import SecurityTestCase, PHONES

LOGIN = '/api/auth/login/'
REFRESH = '/api/auth/refresh/'
FORGOT = '/api/auth/password/forgot/'
CHECK_PHONE = '/api/auth/check-phone/?phone=' + PHONES['victim']
PUBLIC_PAY = '/api/pagamento/00000000-0000-4000-8000-000000000000/'  # UUID válido, inexistente


class LoginThrottleTest(SecurityTestCase):
    """login: 5/min por IP."""

    def test_sixth_login_is_throttled_then_resets(self):
        self.register('victim')
        codes = [
            self.api().post(LOGIN, {'email': 'victim@example.invalid', 'password': 'errada'}, format='json').status_code
            for _ in range(6)
        ]
        self.assertNotIn(429, codes[:5], f'limite estourou cedo: {codes}')
        self.assertEqual(codes[5], 429, f'6a tentativa deveria ser 429: {codes}')

        cache.clear()  # simula a janela deslizando
        after = self.api().post(LOGIN, {'email': 'victim@example.invalid', 'password': 'errada'}, format='json')
        self.assertNotEqual(after.status_code, 429)


class AuthThrottleTest(SecurityTestCase):
    """auth: 10/min por IP (refresh, verify-phone, resend, register, challenge)."""

    def test_eleventh_refresh_is_throttled(self):
        codes = [self.api().post(REFRESH, {}, format='json').status_code for _ in range(11)]
        self.assertNotIn(429, codes[:10], f'limite estourou cedo: {codes}')
        self.assertEqual(codes[10], 429, f'11a deveria ser 429: {codes}')


class PasswordResetThrottleTest(SecurityTestCase):
    """password_reset: 3/min por IP."""

    def test_fourth_forgot_is_throttled_then_resets(self):
        codes = [
            self.api().post(FORGOT, {'email': 'whoever@example.invalid'}, format='json').status_code
            for _ in range(4)
        ]
        self.assertNotIn(429, codes[:3], f'limite estourou cedo: {codes}')
        self.assertEqual(codes[3], 429, f'4a deveria ser 429: {codes}')

        cache.clear()
        self.assertNotEqual(
            self.api().post(FORGOT, {'email': 'whoever@example.invalid'}, format='json').status_code, 429
        )


class PublicPageThrottleTest(SecurityTestCase):
    """public_page: 60/min por IP (página pública de pagamento)."""

    def test_sixtyfirst_request_is_throttled(self):
        codes = [self.api().get(PUBLIC_PAY).status_code for _ in range(61)]
        self.assertNotIn(429, codes[:60], f'limite estourou cedo (primeiros 60): {set(codes[:60])}')
        self.assertEqual(codes[60], 429, f'61a deveria ser 429, foi {codes[60]}')


class PhoneCheckThrottleTest(SecurityTestCase):
    """phone_check: 20/min por usuário autenticado."""

    def test_twentyfirst_check_is_throttled(self):
        tok, _ = self.register('victim')
        client = self.api(tok)
        codes = [client.get(CHECK_PHONE).status_code for _ in range(21)]
        self.assertNotIn(429, codes[:20], f'limite estourou cedo: {codes}')
        self.assertEqual(codes[20], 429, f'21a deveria ser 429: {codes}')


class XffSpoofDoesNotBypassThrottleTest(SecurityTestCase):
    """
    Regressão: rotacionar X-Forwarded-For NÃO pode burlar o rate limit.
    Com NUM_PROXIES=0, o throttle chaveia por REMOTE_ADDR e ignora o XFF do cliente.
    """

    def test_rotating_xff_still_throttles_login(self):
        self.register('victim')
        codes = []
        for i in range(6):
            r = self.api().post(
                LOGIN,
                {'email': 'victim@example.invalid', 'password': 'errada'},
                format='json',
                HTTP_X_FORWARDED_FOR=f'10.0.0.{i}',  # IP falsificado diferente a cada request
            )
            codes.append(r.status_code)
        self.assertEqual(codes[5], 429, f'XFF forjado burlou o throttle: {codes}')
