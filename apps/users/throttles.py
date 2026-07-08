from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    """10 tentativas/minuto por IP em endpoints genéricos de autenticação."""
    scope = 'auth'


class LoginRateThrottle(AnonRateThrottle):
    """5 tentativas/minuto por IP — brute force prevention no login."""
    scope = 'login'


class PasswordResetRateThrottle(AnonRateThrottle):
    """3 tentativas/minuto por IP — previne spam em password reset."""
    scope = 'password_reset'


class PublicPageRateThrottle(AnonRateThrottle):
    """60 requisições/minuto por IP — páginas públicas de pagamento."""
    scope = 'public_page'


class PhoneCheckRateThrottle(UserRateThrottle):
    """20 verificações/minuto por usuário autenticado — lookup de telefone."""
    scope = 'phone_check'
