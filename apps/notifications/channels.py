"""
Canais de envio das notificações. Cada função envia SINCRONAMENTE por um canal;
a orquestração (thread, gating, tratamento de erro) fica no service.
"""
from django.conf import settings
from django.core.mail import send_mail

from apps.groups.whatsapp import send_whatsapp as _send_whatsapp


def enviar_email(*, to: str, assunto: str, corpo: str) -> None:
    send_mail(
        subject=assunto,
        message=corpo,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to],
        fail_silently=False,
    )


def enviar_whatsapp(*, phone: str, corpo: str) -> None:
    _send_whatsapp(phone, corpo)
