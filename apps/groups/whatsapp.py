"""
WhatsApp invite service para convites de grupo.

Padrão backend idêntico ao apps/users/sms.py:
  - ConsoleWhatsAppBackend  → dev (imprime no terminal)
  - TwilioWhatsAppBackend   → prod (Twilio WhatsApp API)

Seleção via settings.WHATSAPP_BACKEND (env var WHATSAPP_BACKEND).

dispatch_group_invite() é o ponto de entrada público — nunca bloqueia,
nunca propaga exceção para o caller.
"""

import importlib
import logging
import re
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalização de telefone
# ---------------------------------------------------------------------------

# Celular brasileiro com 9º dígito: +55 + DDD(2) + 9 + 8 dígitos = 13 dígitos
_BR_MOBILE_9_RE = re.compile(r'^\+55(\d{2})9(\d{8})$')


def _normalize_phone_for_whatsapp(phone: str) -> str:
    """Remove o nono dígito de celulares brasileiros para entrega via WhatsApp.

    O Twilio roteia pelo número pré-2012 (sem o 9 extra):
    +5531999998888 → +553199998888

    Outros países: sem alteração.
    """
    match = _BR_MOBILE_9_RE.match(phone)
    if match:
        return f'+55{match.group(1)}{match.group(2)}'
    return phone


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

_INVITE_BODY = (
    "Olá, {name}! 👋\n\n"
    "*{inviter_name}* te adicionou ao grupo *{group_name}* no Rachei — "
    "o app para dividir despesas com amigos de forma simples e transparente.\n\n"
    "Crie sua conta gratuita e confirme sua participação:\n"
    "{invite_url}\n\n"
    "_Você recebeu esta mensagem porque seu número foi adicionado ao grupo. "
    "Se não conhece essa pessoa, pode ignorar com segurança._"
)

# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class ConsoleWhatsAppBackend:
    """Usado em desenvolvimento — apenas imprime no terminal."""

    def send(self, to: str, body: str) -> None:
        print(
            f'\n[WHATSAPP] Para: {to}\n'
            f'{"-" * 60}\n{body}\n{"-" * 60}\n',
            flush=True,
        )


class TwilioWhatsAppBackend:
    """Envia via Twilio WhatsApp API."""

    def send(self, to: str, body: str) -> None:
        from twilio.rest import Client

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=body,
            from_=settings.TWILIO_WHATSAPP_FROM,   # ex: 'whatsapp:+14155238886'
            to=f'whatsapp:{to}',
        )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _get_backend():
    path = getattr(
        settings,
        'WHATSAPP_BACKEND',
        'apps.groups.whatsapp.ConsoleWhatsAppBackend',
    )
    module_path, class_name = path.rsplit('.', 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def _mask_phone(phone: str) -> str:
    """Mascara para logs: +5531999998888 → +55****8888."""
    if len(phone) <= 6:
        return '****'
    return phone[:3] + '****' + phone[-4:]


def _send(phone: str, name: str, inviter_name: str, group_name: str) -> None:
    invite_url = getattr(settings, 'APP_INVITE_URL', 'https://rachei.app/cadastro')
    body = _INVITE_BODY.format(
        name=name,
        inviter_name=inviter_name,
        group_name=group_name,
        invite_url=invite_url,
    )
    normalized = _normalize_phone_for_whatsapp(phone)
    try:
        _get_backend().send(normalized, body)
        logger.info('whatsapp_invite_sent phone=%s group=%r', _mask_phone(phone), group_name)
    except Exception:
        logger.exception(
            'whatsapp_invite_failed phone=%s group=%r', _mask_phone(phone), group_name
        )


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def dispatch_group_invite(
    *,
    phone: str,
    name: str,
    inviter_name: str,
    group_name: str,
) -> None:
    """Dispara convite WhatsApp em thread daemon.

    Nunca bloqueia a resposta HTTP. Nunca propaga exceção.
    Pronto para substituição por tarefa Celery:
        celery_task.delay(phone, name, inviter_name, group_name)
    """
    threading.Thread(
        target=_send,
        args=(phone, name, inviter_name, group_name),
        daemon=True,
        name=f'wa-invite-{_mask_phone(phone)}',
    ).start()
