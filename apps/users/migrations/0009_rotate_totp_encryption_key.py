"""
Data migration: re-criptografa secrets TOTP de uma chave antiga para a nova.

Como executar:
  TOTP_OLD_ENCRYPTION_KEY=<chave_antiga> python manage.py migrate users 0009

  Sem TOTP_OLD_ENCRYPTION_KEY: migration pulada (no-op seguro — útil em CI).
  Sem TOTP_ENCRYPTION_KEY: migration pulada.
  Chaves iguais: migration pulada.

Contagem obrigatória: rotacionados, pulados (chave diferente), vazios.
Nenhuma linha falha silenciosamente — erros levantam RuntimeError e revertem.
"""
import binascii
import logging
import os

from django.db import migrations

logger = logging.getLogger(__name__)


def rotate_key_forward(apps, schema_editor):
    from cryptography.fernet import Fernet, InvalidToken
    from django.conf import settings as django_settings

    old_key_str = os.environ.get('TOTP_OLD_ENCRYPTION_KEY', '')
    if not old_key_str:
        logger.info('rotate_key_forward: TOTP_OLD_ENCRYPTION_KEY ausente — migration pulada (no-op).')
        return

    new_key_str = getattr(django_settings, 'TOTP_ENCRYPTION_KEY', '')
    if not new_key_str:
        logger.info('rotate_key_forward: TOTP_ENCRYPTION_KEY ausente — migration pulada (no-op).')
        return

    old_key = old_key_str.encode() if isinstance(old_key_str, str) else old_key_str
    new_key = new_key_str.encode() if isinstance(new_key_str, str) else new_key_str

    if new_key == old_key:
        logger.info('rotate_key_forward: chaves idênticas — sem rotação necessária.')
        return

    old_fernet = Fernet(old_key)
    new_fernet = Fernet(new_key)

    rotated = 0
    skipped_empty = 0
    skipped_not_old_key = 0
    errors = []

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT tfa_id, tfa_secret FROM configs_2fa WHERE tfa_secret != ''")
        rows = cursor.fetchall()
        total = len(rows)

        for pk, secret in rows:
            if not secret:
                skipped_empty += 1
                logger.debug('rotate_key_forward: tfa_id=%s — secret vazio, pulado', pk)
                continue

            try:
                plaintext = old_fernet.decrypt(secret.encode()).decode()
            except (InvalidToken, binascii.Error):
                skipped_not_old_key += 1
                logger.debug(
                    'rotate_key_forward: tfa_id=%s — não criptografado com TOTP_OLD_ENCRYPTION_KEY, pulado',
                    pk,
                )
                continue
            except UnicodeDecodeError as exc:
                errors.append(f'tfa_id={pk}: UnicodeDecodeError após decrypt: {exc}')
                continue

            try:
                new_encrypted = new_fernet.encrypt(plaintext.encode()).decode()
                cursor.execute(
                    'UPDATE configs_2fa SET tfa_secret = %s WHERE tfa_id = %s',
                    [new_encrypted, pk],
                )
                rotated += 1
            except Exception as exc:
                errors.append(f'tfa_id={pk}: erro ao re-criptografar: {type(exc).__name__}: {exc}')

    logger.info(
        'rotate_key_forward concluído: total=%d | rotacionados=%d | '
        'pulados_chave_diferente=%d | pulados_vazios=%d',
        total, rotated, skipped_not_old_key, skipped_empty,
    )

    if errors:
        for err in errors:
            logger.error('rotate_key_forward: LINHA COM FALHA — %s', err)
        raise RuntimeError(
            f'rotate_key_forward: {len(errors)} linha(s) com falha. '
            f'Transação revertida. Verifique os logs acima.'
        )


def rotate_key_reverse(apps, schema_editor):
    """Reverter: re-criptografa de TOTP_ENCRYPTION_KEY → TOTP_OLD_ENCRYPTION_KEY."""
    from cryptography.fernet import Fernet, InvalidToken
    from django.conf import settings as django_settings

    old_key_str = os.environ.get('TOTP_OLD_ENCRYPTION_KEY', '')
    new_key_str = getattr(django_settings, 'TOTP_ENCRYPTION_KEY', '')

    if not old_key_str or not new_key_str:
        logger.info('rotate_key_reverse: chaves ausentes — reverse pulado (no-op).')
        return

    old_key = old_key_str.encode() if isinstance(old_key_str, str) else old_key_str
    new_key = new_key_str.encode() if isinstance(new_key_str, str) else new_key_str

    if new_key == old_key:
        return

    old_fernet = Fernet(old_key)
    new_fernet = Fernet(new_key)

    rotated = 0
    skipped = 0
    errors = []

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT tfa_id, tfa_secret FROM configs_2fa WHERE tfa_secret != ''")
        rows = cursor.fetchall()
        for pk, secret in rows:
            if not secret:
                continue
            try:
                plaintext = new_fernet.decrypt(secret.encode()).decode()
            except (InvalidToken, binascii.Error):
                skipped += 1
                continue
            except UnicodeDecodeError as exc:
                errors.append(f'tfa_id={pk}: UnicodeDecodeError: {exc}')
                continue
            try:
                old_encrypted = old_fernet.encrypt(plaintext.encode()).decode()
                cursor.execute(
                    'UPDATE configs_2fa SET tfa_secret = %s WHERE tfa_id = %s',
                    [old_encrypted, pk],
                )
                rotated += 1
            except Exception as exc:
                errors.append(f'tfa_id={pk}: {type(exc).__name__}: {exc}')

    logger.info('rotate_key_reverse concluído: rotacionados=%d pulados=%d', rotated, skipped)
    if errors:
        for err in errors:
            logger.error('rotate_key_reverse: FALHA — %s', err)
        raise RuntimeError(f'rotate_key_reverse: {len(errors)} falha(s).')


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_encrypt_totp_secrets'),
    ]

    operations = [
        migrations.RunPython(rotate_key_forward, rotate_key_reverse),
    ]
