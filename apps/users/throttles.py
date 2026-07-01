from rest_framework.throttling import AnonRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    """10 tentativas/minuto por IP em endpoints de autenticação."""
    scope = 'auth'
