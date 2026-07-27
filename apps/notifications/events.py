"""
Eventos de notificação — a matriz aprovada (o que enviar, para quem, por qual
canal e sob qual preferência). Cada função monta a mensagem e delega ao service.

Regra: só se notifica ativamente a AÇÃO DE TERCEIRO; nunca o que o próprio
usuário fez (isso fica só no feed).
"""
from .service import EMAIL, WHATSAPP, notificar


def _reais(cents: int) -> str:
    return f'R$ {cents / 100:.2f}'.replace('.', ',')


def _nome(user) -> str:
    return (user.get_full_name() or user.username) if user else 'alguém'


def incluido_em_divida(*, devedor, credor, descricao, grupo_nome, valor_cents):
    """Você foi incluído numa dívida. → devedor · cobranças · e-mail + WhatsApp."""
    notificar(
        user=devedor, categoria='cobrancas',
        assunto=f'Nova dívida no Rachei: {descricao}',
        corpo=(
            f'{_nome(credor)} registrou que você deve {_reais(valor_cents)} '
            f'em "{descricao}" (grupo {grupo_nome}). Abra o Rachei para ver os detalhes.'
        ),
        canais=(EMAIL, WHATSAPP),
    )


def cobranca_enviada(*, devedor, credor, descricao, valor_cents):
    """Cobrança/link enviado. → devedor · cobranças · WhatsApp."""
    notificar(
        user=devedor, categoria='cobrancas',
        assunto=f'Cobrança no Rachei: {descricao}',
        corpo=(
            f'{_nome(credor)} está cobrando {_reais(valor_cents)} de "{descricao}". '
            f'Abra o Rachei para pagar ou combinar.'
        ),
        canais=(WHATSAPP,),
    )


def pagamento_declarado(*, credor, devedor, descricao, valor_cents):
    """Devedor declarou pagamento (aguardando você). → credor · confirmações · e-mail + WhatsApp."""
    notificar(
        user=credor, categoria='confirmacoes',
        assunto=f'Pagamento a confirmar: {descricao}',
        corpo=(
            f'{_nome(devedor)} declarou o pagamento de {_reais(valor_cents)} '
            f'em "{descricao}". Confirme o recebimento no Rachei.'
        ),
        canais=(EMAIL, WHATSAPP),
    )


def pagamento_confirmado(*, devedor, credor, descricao, valor_cents):
    """Seu pagamento foi confirmado. → devedor · confirmações · e-mail."""
    notificar(
        user=devedor, categoria='confirmacoes',
        assunto=f'Pagamento confirmado: {descricao}',
        corpo=(
            f'{_nome(credor)} confirmou o recebimento de {_reais(valor_cents)} '
            f'em "{descricao}". Sua parte está quitada.'
        ),
        canais=(EMAIL,),
    )


def comprovante_rejeitado(*, devedor, credor, descricao, valor_cents):
    """Seu comprovante foi rejeitado. → devedor · confirmações · e-mail + WhatsApp."""
    notificar(
        user=devedor, categoria='confirmacoes',
        assunto=f'Pagamento não confirmado: {descricao}',
        corpo=(
            f'{_nome(credor)} não confirmou o pagamento de {_reais(valor_cents)} '
            f'em "{descricao}". Verifique e tente novamente no Rachei.'
        ),
        canais=(EMAIL, WHATSAPP),
    )


def compensacao_proposta(*, destinatario, proponente):
    """Proposta de compensação recebida. → destinatário · confirmações · e-mail + WhatsApp."""
    notificar(
        user=destinatario, categoria='confirmacoes',
        assunto='Proposta de compensação no Rachei',
        corpo=(
            f'{_nome(proponente)} propôs compensar dívidas de vocês. '
            f'Abra o Rachei para revisar e aceitar ou recusar.'
        ),
        canais=(EMAIL, WHATSAPP),
    )


def compensacao_confirmada(*, proponente, confirmador):
    """Sua compensação foi confirmada. → proponente · confirmações · e-mail."""
    notificar(
        user=proponente, categoria='confirmacoes',
        assunto='Compensação confirmada no Rachei',
        corpo=(
            f'{_nome(confirmador)} confirmou a compensação que você propôs. '
            f'As dívidas foram acertadas.'
        ),
        canais=(EMAIL,),
    )


def lembrete_pendente(*, devedor, credor, descricao, valor_cents, dias):
    """Lembrete de parcela pendente. → devedor · lembretes · WhatsApp."""
    notificar(
        user=devedor, categoria='lembretes',
        assunto=f'Lembrete: {descricao} em aberto',
        corpo=(
            f'Você ainda deve {_reais(valor_cents)} a {_nome(credor)} '
            f'em "{descricao}" há {dias} dias. Abra o Rachei para acertar.'
        ),
        canais=(WHATSAPP,),
    )
