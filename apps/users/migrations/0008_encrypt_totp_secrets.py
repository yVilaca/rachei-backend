"""
Data migration: criptografa secrets TOTP existentes com Fernet.

Usa SQL direto para bypassar o ORM e evitar dupla-criptografia
(o EncryptedCharField criptografaria no get_prep_value se usássemos o ORM).

Pré-requisito: TOTP_ENCRYPTION_KEY deve estar definida no ambiente antes de migrar.
"""
from django.db import migrations


def encrypt_existing_secrets(apps, schema_editor):
    from apps.users.fields import get_fernet
    from cryptography.fernet import InvalidToken

    try:
        fernet = get_fernet()
    except Exception:
        # Sem chave configurada — pula (secrets permanecerão plaintext até a chave ser definida)
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT tfa_id, tfa_secret FROM configs_2fa WHERE tfa_secret != ''")
        rows = cursor.fetchall()
        for pk, secret in rows:
            if not secret:
                continue
            try:
                fernet.decrypt(secret.encode())
                # Já está criptografado — pula
            except (InvalidToken, Exception):
                # Plaintext — criptografa
                encrypted = fernet.encrypt(secret.encode()).decode()
                cursor.execute(
                    "UPDATE configs_2fa SET tfa_secret = %s WHERE tfa_id = %s",
                    [encrypted, pk],
                )


def decrypt_existing_secrets(apps, schema_editor):
    """Reverse: descriptografa para plaintext (rollback)."""
    from apps.users.fields import get_fernet
    try:
        fernet = get_fernet()
    except Exception:
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT tfa_id, tfa_secret FROM configs_2fa WHERE tfa_secret != ''")
        rows = cursor.fetchall()
        for pk, secret in rows:
            if not secret:
                continue
            try:
                plaintext = fernet.decrypt(secret.encode()).decode()
                cursor.execute(
                    "UPDATE configs_2fa SET tfa_secret = %s WHERE tfa_id = %s",
                    [plaintext, pk],
                )
            except Exception:
                pass  # já estava em plaintext


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_twofactorconfig_security_fields'),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_secrets, decrypt_existing_secrets),
    ]
