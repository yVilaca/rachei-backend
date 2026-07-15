"""
Observabilidade — request-id (correlação), scrubbing de dados sensíveis,
inicialização do Sentry e endpoint de health.

Tudo é no-op quando os tokens/DSN não estão no ambiente, para que dev local e
CI rodem sem depender de serviços externos.
"""
import contextvars
import logging
import os
import uuid

# ── Request ID (correlação front↔back e entre logs) ──────────────────────────
request_id_var = contextvars.ContextVar('request_id', default='-')
_REQUEST_ID_META = 'HTTP_X_REQUEST_ID'
_RESPONSE_HEADER = 'X-Request-ID'


class RequestIDMiddleware:
    """Garante um ID por requisição: reusa o X-Request-ID do cliente ou gera um."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid = request.META.get(_REQUEST_ID_META) or uuid.uuid4().hex
        request.request_id = rid
        token = request_id_var.set(rid)
        try:
            try:
                import sentry_sdk
                sentry_sdk.set_tag('request_id', rid)
            except Exception:
                pass
            response = self.get_response(request)
            response[_RESPONSE_HEADER] = rid
            return response
        finally:
            request_id_var.reset(token)


class RequestIDFilter(logging.Filter):
    """Injeta o request_id em cada registro de log."""

    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


# ── Scrubbing de dados sensíveis (LGPD + app financeiro) ─────────────────────
SENSITIVE_SUBSTRINGS = (
    'password', 'senha', 'token', 'authorization', 'cookie', 'secret',
    'totp', 'otp', 'code', 'codigo', 'csrf', 'phone', 'telefone', 'cpf',
)
REDACTED = '[Filtrado]'


def _is_sensitive(key) -> bool:
    k = str(key).lower()
    return any(s in k for s in SENSITIVE_SUBSTRINGS)


def scrub(obj):
    """Redige recursivamente valores de chaves sensíveis."""
    if isinstance(obj, dict):
        return {k: (REDACTED if _is_sensitive(k) else scrub(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    return obj


# ── Sentry ───────────────────────────────────────────────────────────────────
def _before_send(event, hint):
    """Remove segredos antes de enviar ao Sentry."""
    req = event.get('request') or {}
    headers = req.get('headers')
    if isinstance(headers, dict):
        req['headers'] = {k: (REDACTED if _is_sensitive(k) else v) for k, v in headers.items()}
    if isinstance(req.get('data'), (dict, list)):
        req['data'] = scrub(req['data'])
    if 'cookies' in req:
        req['cookies'] = REDACTED
    if req:
        event['request'] = req
    if isinstance(event.get('extra'), dict):
        event['extra'] = scrub(event['extra'])
    return event


def init_sentry():
    """Inicializa o Sentry se houver DSN; caso contrário, no-op (dev/CI)."""
    dsn = os.getenv('SENTRY_DSN', '').strip()
    if not dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration()],
        environment=os.getenv('SENTRY_ENVIRONMENT', 'development'),
        release=os.getenv('SENTRY_RELEASE') or os.getenv('GIT_SHA') or None,
        traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0.1')),
        send_default_pii=False,       # nunca envia PII automaticamente
        before_send=_before_send,
    )


# ── Health check (alvo do monitor de uptime) ─────────────────────────────────
def health_view(request):
    """GET /health/ — readiness: verifica conexão com o banco. Público, sem auth."""
    from django.db import connection
    from django.http import JsonResponse
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False
    return JsonResponse(
        {'status': 'ok' if db_ok else 'degraded', 'database': db_ok},
        status=200 if db_ok else 503,
    )
