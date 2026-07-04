"""
Data migration: re-criptografa secrets TOTP da chave antiga (hardcoded/comprometida)
para a nova chave fornecida via TOTP_ENCRYPTION_KEY.

Como executar:
  1. Defina TOTP_ENCRYPTION_KEY=<nova_chave> no ambiente
  2. python manage.py migrate users 0009

A chave antiga (OLD_KEY abaixo) estava hardcoded em settings.py e é agora tratada
como comprometida. Após esta migration, ela não é mais usada pelo sistema.

A migration é idempotente: se a nova chave for igual à antiga, ou se não estiver
configurada, ela não faz nada.
"""
from django.db import migrations


# Chave antiga que estava hardcoded em settings.py — já pública no histórico do git.
# Está aqui APENAS para permitir a descriptografia dos dados já existentes.
_OLD_KEY = b'YNqvfjrYdzvwqJQQiHQCV_-2eeWNfya4UAHsxiNdNwU='


def rotate_key_forward(apps, schema_editor):
    from cryptography.fernet import Fernet, InvalidToken
    from django.conf import settings as django_settings

    new_key_str = getattr(django_settings, 'TOTP_ENCRYPTION_KEY', '')
    if not new_key_str:
        return  # chave nova não configurada — pula (ex: ambiente de CI sem a env var)

    new_key = new_key_str.encode() if isinstance(new_key_str, str) else new_key_str

    if new_key == _OLD_KEY:
        return  # chaves idênticas — sem rotação necessária (ex: testes com @override_settings)

    old_fernet = Fernet(_OLD_KEY)
    new_fernet = Fernet(new_key)

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT tfa_id, tfa_secret FROM configs_2fa WHERE tfa_secret != ''")
        rows = cursor.fetchall()
        for pk, secret in rows:
            if not secret:
                continue
            try:
                plaintext = old_fernet.decrypt(secret.encode()).decode()
            except (InvalidToken, Exception):
                # Não estava criptografado com a chave antiga — ignora
                continue
            new_encrypted = new_fernet.encrypt(plaintext.encode()).decode()
            cursor.execute(
                'UPDATE configs_2fa SET tfa_secret = %s WHERE tfa_id = %s',
                [new_encrypted, pk],
            )


def rotate_key_reverse(apps, schema_editor):
    """Reverter: re-criptografa com a chave antiga (rollback de emergência)."""
    from cryptography.fernet import Fernet, InvalidToken
    from django.conf import settings as django_settings

    new_key_str = getattr(django_settings, 'TOTP_ENCRYPTION_KEY', '')
    if not new_key_str:
        return

    new_key = new_key_str.encode() if isinstance(new_key_str, str) else new_key_str
    if new_key == _OLD_KEY:
        return

    old_fernet = Fernet(_OLD_KEY)
    new_fernet = Fernet(new_key)

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT tfa_id, tfa_secret FROM configs_2fa WHERE tfa_secret != ''")
        rows = cursor.fetchall()
        for pk, secret in rows:
            if not secret:
                continue
            try:
                plaintext = new_fernet.decrypt(secret.encode()).decode()
            except (InvalidToken, Exception):
                continue
            old_encrypted = old_fernet.encrypt(plaintext.encode()).decode()
            cursor.execute(
                'UPDATE configs_2fa SET tfa_secret = %s WHERE tfa_id = %s',
                [old_encrypted, pk],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_encrypt_totp_secrets'),
    ]

    operations = [
        migrations.RunPython(rotate_key_forward, rotate_key_reverse),
    ]
