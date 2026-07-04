from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def get_fernet() -> Fernet:
    key = getattr(settings, 'TOTP_ENCRYPTION_KEY', '')
    if not key:
        raise ImproperlyConfigured(
            'TOTP_ENCRYPTION_KEY must be set. '
            'Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


class EncryptedCharField(models.CharField):
    """CharField que criptografa o valor com Fernet antes de salvar e decifra ao ler.

    O valor armazenado no banco é um token Fernet (base64url, ~200 chars para secrets TOTP).
    O valor Python é sempre o texto original (ex: 'JBSWY3DPEHPK3PXP').

    Fallback de leitura: se o valor no banco não for um token Fernet válido (ex: plaintext
    de antes da migration de criptografia), retorna o valor como está.
    """

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return get_fernet().decrypt(value.encode()).decode()
        except (InvalidToken, Exception):
            return value  # valor plaintext pré-migration

    def get_prep_value(self, value):
        if not value:
            return value
        return get_fernet().encrypt(value.encode()).decode()
