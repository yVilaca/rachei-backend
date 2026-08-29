"""
Settings de TESTE — herda tudo de settings.py e só acelera.

Não muda comportamento de negócio: apenas troca o hasher de senha por um
rápido (os testes criam muitos usuários, e o PBKDF2 real domina o tempo) e
silencia logs ruidosos. Mesmo banco (Postgres) e mesmas regras de sempre.
"""
import logging

from .settings import *  # noqa: F401,F403

# Hash rápido só para testes (padrão de mercado). Login/validação seguem corretos.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Chave fixa e longa (>=32 bytes) para a suíte: evita o InsecureKeyLengthWarning
# do PyJWT ao assinar tokens nos testes de auth. Não é segredo real.
SECRET_KEY = 'test-insecure-fixed-key-for-tests-only-0123456789abcdef'

# Silencia logs de app (SMS de console, INFO de migrations) durante a suíte.
logging.disable(logging.CRITICAL)

# Notificações: síncronas e capturadas em memória para asserção nos testes.
NOTIFICACOES_SINCRONAS = True
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
WHATSAPP_BACKEND = 'apps.groups.whatsapp.LocMemWhatsAppBackend'
