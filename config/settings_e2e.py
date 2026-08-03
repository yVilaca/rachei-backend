"""
Settings para os testes E2E full-stack (Playwright).

Sobe um Django REAL contra um banco DESCARTÁVEL (rachei_e2e) — nunca o de dev.
Envios externos são fake, throttles desligados, hasher rápido, e um app extra
(apps.e2e) expõe o endpoint de reset/seed usado pelos testes.
"""
import logging
import os

# Sem observabilidade externa nos testes (evita ruído/envios). Definido ANTES de
# importar settings — load_dotenv não sobrescreve variáveis já presentes.
os.environ['SENTRY_DSN'] = ''
os.environ['BETTERSTACK_SOURCE_TOKEN'] = ''

from .settings import *  # noqa: E402,F401,F403
from .settings import INSTALLED_APPS, REST_FRAMEWORK  # noqa: E402

# Banco descartável — isolado do desenvolvimento.
DATABASES['default']['NAME'] = 'rachei_e2e'  # noqa: F405
# Reutiliza conexões no servidor vivo (menos connects novos = mais estável).
DATABASES['default']['CONN_MAX_AGE'] = 60  # noqa: F405

DEBUG = True
E2E_MODE = True  # habilita o endpoint de reset/seed (apps.e2e)

# App de suporte a E2E (seed/reset) — só existe neste settings.
INSTALLED_APPS = [*INSTALLED_APPS, 'apps.e2e']

# Envios externos sempre fake.
SMS_BACKEND = 'apps.users.sms.ConsoleSmsBackend'
WHATSAPP_BACKEND = 'apps.groups.whatsapp.ConsoleWhatsAppBackend'
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
NOTIFICACOES_SINCRONAS = False

# Hasher rápido (login continua correto).
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Throttles desligados — não atrapalham a automação.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_THROTTLE_RATES': {
        k: None for k in ('anon', 'public_page', 'user', 'auth', 'login', 'password_reset', 'phone_check')
    },
}

logging.disable(logging.INFO)
