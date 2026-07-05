import importlib

from django.conf import settings


def send_sms(to: str, body: str) -> None:
    """Envia SMS via backend configurado em SMS_BACKEND."""
    backend_path = getattr(settings, 'SMS_BACKEND', 'apps.users.sms.ConsoleSmsBackend')
    module_path, class_name = backend_path.rsplit('.', 1)
    module = importlib.import_module(module_path)
    backend_cls = getattr(module, class_name)
    backend_cls().send(to, body)


class ConsoleSmsBackend:
    def send(self, to: str, body: str) -> None:
        print(f'\n[SMS] Para: {to}\n      Mensagem: {body}\n', flush=True)


class TwilioSmsBackend:
    def send(self, to: str, body: str) -> None:
        from twilio.rest import Client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(body=body, from_=settings.TWILIO_FROM, to=to)
