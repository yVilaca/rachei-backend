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

# Silencia logs de app (SMS de console, INFO de migrations) durante a suíte.
logging.disable(logging.CRITICAL)
