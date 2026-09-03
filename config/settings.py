from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

from django.core.exceptions import ImproperlyConfigured  # noqa: E402

# Fail-safe por padrão: DEBUG desligado a menos que explicitamente ligado, e a
# aplicação recusa subir em produção com a SECRET_KEY de exemplo (chave de
# assinatura JWT previsível). Dev/testes definem DEBUG=True via .env/settings.
_INSECURE_SECRET = 'django-insecure-change-me'
SECRET_KEY = os.getenv('SECRET_KEY', _INSECURE_SECRET)
DEBUG = os.getenv('DEBUG', 'False') == 'True'
if not DEBUG and SECRET_KEY == _INSECURE_SECRET:
    raise ImproperlyConfigured(
        'SECRET_KEY não configurada: defina SECRET_KEY no ambiente antes de rodar com DEBUG=False.'
    )
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    # Local
    'apps.users',
    'apps.groups',
    'apps.debts',
    'apps.payments',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'config.observability.RequestIDMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# PostgreSQL em todos os ambientes (dev, CI e produção). Sem fallback para
# SQLite: uma config ausente/errada falha alto na conexão em vez de rodar
# silenciosamente em outro motor de banco.
DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.getenv('DB_NAME', 'rachei'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'CONN_MAX_AGE': int(os.getenv('CONN_MAX_AGE', '0')),
        # Negocia UTF-8 já no startup: sem isso, o libpq pode devolver mensagens
        # no code page do SO (ex.: cp1252 no Windows pt-BR) e o psycopg2 quebra
        # ao decodificá-las como UTF-8 na conexão.
        'OPTIONS': {'client_encoding': 'UTF8'},
    }
}

# Cache — backend do rate-limit (throttle) do DRF. Precisa ser COMPARTILHADO
# entre workers em produção: LocMem é por-processo, então com gunicorn -w N cada
# worker teria seu próprio contador e o limite de login (5/min) viraria 5*N,
# furando o anti-brute-force. Redis via REDIS_URL em prod; LocMem só em dev.
REDIS_URL = os.getenv('REDIS_URL', '')
if REDIS_URL:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': REDIS_URL}}
elif DEBUG:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
else:
    raise ImproperlyConfigured(
        'REDIS_URL é obrigatória em produção: o throttle precisa de cache compartilhado entre workers.'
    )

AUTH_USER_MODEL = 'users.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'EXCEPTION_HANDLER': 'rest_framework.views.exception_handler',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'public_page': '60/minute',
        'user': '1000/hour',
        'auth': '10/minute',
        'login': '5/minute',
        'password_reset': '3/minute',
        'phone_check': '20/minute',
    },
    # Nº de proxies confiáveis à frente da app. Default 0: throttle usa REMOTE_ADDR
    # e IGNORA o X-Forwarded-For do cliente (senão o header é forjável e burla o
    # rate limit). Em produção atrás de N proxies (ex: nginx), setar NUM_PROXIES=N
    # via .env para ler o IP real do cliente na posição correta do XFF.
    'NUM_PROXIES': int(os.getenv('NUM_PROXIES', '0')),
}

# JWT
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
}

# CORS
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS', 'http://localhost:5173'
).split(',')
CORS_ALLOW_CREDENTIALS = True  # obrigatório para HttpOnly cookie cross-port no mesmo hostname

# Headers de tracing distribuído do Sentry (front→back) precisam ser permitidos
# no preflight; sem isso o navegador bloqueia a requisição real (CORS error).
CORS_ALLOW_HEADERS = (*default_headers, 'sentry-trace', 'baggage')

# Deixa o front ler o ID de correlação da resposta.
CORS_EXPOSE_HEADERS = ('X-Request-ID',)

# Security headers (gerenciados pelo SecurityMiddleware do Django)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

# Em produção (HTTPS), setar via .env:
#   SECURE_SSL_REDIRECT=True
#   SECURE_HSTS_SECONDS=31536000
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'False') == 'True'
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

# Atrás de proxy/TLS-terminator (nginx/Caddy): sem isto o Django não reconhece o
# X-Forwarded-Proto, request.is_secure() é sempre False e SECURE_SSL_REDIRECT
# entra em loop infinito de redirect. O proxy DEVE sobrescrever esse header.
if os.getenv('USE_X_FORWARDED_PROTO', 'True' if not DEBUG else 'False') == 'True':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Cookies de sessão seguros (não usados com JWT, mas defensivamente boas práticas).
# Secure fora de dev: admin usa sessão+CSRF por cookie e não podem trafegar em HTTP.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False  # CSRF cookie precisa ser lido pelo JS (se CSRF ativo)
CSRF_COOKIE_SECURE = not DEBUG

# URL do admin — configurável via env para não ficar em /admin/ padrão
ADMIN_URL = os.getenv('ADMIN_URL', 'admin/')

# E-mail
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Rachei <noreply@rachei.app>')

# Criptografia TOTP (Fernet) — OBRIGATÓRIA via variável de ambiente.
# Gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Sem esta variável, qualquer operação 2FA lança ImproperlyConfigured (ver apps/users/fields.py).
TOTP_ENCRYPTION_KEY = os.getenv('TOTP_ENCRYPTION_KEY', '')

# SMS
# Em dev: ConsoleSmsBackend (imprime no terminal)
# Em prod: setar SMS_BACKEND=apps.users.sms.TwilioSmsBackend + credenciais Twilio
SMS_BACKEND = os.getenv('SMS_BACKEND', 'apps.users.sms.ConsoleSmsBackend')
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM = os.getenv('TWILIO_FROM', '')                        # SMS: +55...
TWILIO_WHATSAPP_FROM = os.getenv('TWILIO_WHATSAPP_FROM', '')      # WhatsApp: whatsapp:+14155238886

# WhatsApp backend (mesmo padrão do SMS_BACKEND)
# Dev:  apps.groups.whatsapp.ConsoleWhatsAppBackend  (padrão)
# Prod: apps.groups.whatsapp.TwilioWhatsAppBackend
WHATSAPP_BACKEND = os.getenv('WHATSAPP_BACKEND', 'apps.groups.whatsapp.ConsoleWhatsAppBackend')

# Notificações ativas (e-mail/WhatsApp). Assíncronas por padrão (thread daemon);
# os testes ligam NOTIFICACOES_SINCRONAS para asserção determinística.
NOTIFICACOES_SINCRONAS = os.getenv('NOTIFICACOES_SINCRONAS', 'False') == 'True'

# Lembretes de parcela em aberto (comando enviar_lembretes, idempotente):
# envia após LEMBRETE_APOS_DIAS de atraso e repete a cada LEMBRETE_INTERVALO_DIAS.
LEMBRETE_APOS_DIAS = int(os.getenv('LEMBRETE_APOS_DIAS', '3'))
LEMBRETE_INTERVALO_DIAS = int(os.getenv('LEMBRETE_INTERVALO_DIAS', '4'))

# URL base do frontend — usada nos convites WhatsApp
APP_INVITE_URL = os.getenv('APP_INVITE_URL', 'https://rachei.app/cadastro')

# Logging — estruturado (JSON em prod), com request_id e envio ao Better Stack.
# Dev: console legível. Prod: JSON. Better Stack só quando o token está presente.
BETTERSTACK_SOURCE_TOKEN = os.getenv('BETTERSTACK_SOURCE_TOKEN', '').strip()
BETTERSTACK_HOST = os.getenv('BETTERSTACK_HOST', 'https://in.logs.betterstack.com').strip()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'request_id': {'()': 'config.observability.RequestIDFilter'},
    },
    'formatters': {
        'simple': {
            'format': '[{levelname}] {name} {request_id}: {message}',
            'style': '{',
        },
        'json': {
            '()': 'pythonjsonlogger.json.JsonFormatter',
            'fmt': '%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'filters': ['request_id'],
            'formatter': 'simple' if DEBUG else 'json',
        },
    },
    'loggers': {
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

# Envia logs ao Better Stack apenas se o token estiver configurado.
if BETTERSTACK_SOURCE_TOKEN:
    LOGGING['handlers']['betterstack'] = {
        'class': 'logtail.LogtailHandler',
        'source_token': BETTERSTACK_SOURCE_TOKEN,
        'host': BETTERSTACK_HOST,
        'filters': ['request_id'],
        'level': 'INFO',
    }
    for _logger in ('apps', 'django.request'):
        LOGGING['loggers'][_logger]['handlers'].append('betterstack')

# ── Sentry (erros + performance) — no-op sem SENTRY_DSN ──────────────────────
from config.observability import init_sentry  # noqa: E402
init_sentry()
