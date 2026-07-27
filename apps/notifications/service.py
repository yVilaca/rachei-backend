"""
Dispatch central de notificações.

`notificar()` respeita a preferência da categoria no perfil e os canais
disponíveis (e-mail sempre; WhatsApp só com telefone verificado). Nunca
bloqueia a resposta e nunca propaga exceção — falha de canal é logada.
"""
import logging
import threading

from django.conf import settings

from .channels import enviar_email, enviar_whatsapp

logger = logging.getLogger('apps.notifications')

# Categoria da notificação → campo de preferência no User.
CATEGORIA_CAMPO = {
    'cobrancas': 'notif_cobracas',
    'confirmacoes': 'notif_confirmacoes',
    'lembretes': 'notif_lembretes',
}

EMAIL = 'email'
WHATSAPP = 'whatsapp'


def _pode_whatsapp(user) -> bool:
    return bool(getattr(user, 'phone', None) and getattr(user, 'phone_verified', False))


def notificar(*, user, categoria, assunto, corpo, canais=(EMAIL, WHATSAPP)):
    """
    Notifica `user` sobre um evento da `categoria`, pelos `canais` indicados.

    - Silenciosa se o usuário desativou a categoria no perfil.
    - E-mail exige `user.email`; WhatsApp exige telefone verificado.
    - Assíncrona (thread daemon) por padrão; síncrona em testes
      (settings.NOTIFICACOES_SINCRONAS=True).
    """
    campo = CATEGORIA_CAMPO.get(categoria)
    if campo and not getattr(user, campo, True):
        logger.info('notif_suprimida categoria=%s user=%s (preferência)', categoria, user.pk)
        return

    def _run():
        if EMAIL in canais and getattr(user, 'email', None):
            try:
                enviar_email(to=user.email, assunto=assunto, corpo=corpo)
            except Exception:
                logger.exception('notif_email_falhou categoria=%s user=%s', categoria, user.pk)
        if WHATSAPP in canais and _pode_whatsapp(user):
            try:
                enviar_whatsapp(phone=user.phone, corpo=corpo)
            except Exception:
                logger.exception('notif_whatsapp_falhou categoria=%s user=%s', categoria, user.pk)

    if getattr(settings, 'NOTIFICACOES_SINCRONAS', False):
        _run()
    else:
        threading.Thread(target=_run, daemon=True, name=f'notif-{user.pk}').start()
