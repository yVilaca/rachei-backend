from datetime import timedelta

from rest_framework_simplejwt.tokens import Token


class TwoFAPendingToken(Token):
    """Token de curta duração emitido após login bem-sucedido quando 2FA é necessário.
    Não é um access token — não pode acessar endpoints protegidos."""
    token_type = '2fa_pending'
    lifetime = timedelta(minutes=15)
