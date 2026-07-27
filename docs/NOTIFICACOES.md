# Notificações ativas (e-mail / WhatsApp)

O feed em `/api/atividade/` é **derivado** (pull). Além dele, o backend **envia
ativamente** e-mail e WhatsApp em eventos importantes, respeitando as
preferências do perfil.

## O que é enviado (matriz)

| Evento (gatilho) | Recebe | Categoria (preferência) | Canais |
|---|---|---|---|
| Você foi incluído numa dívida | devedor | cobranças | e-mail + WhatsApp |
| Cobrança / link enviado | devedor | cobranças | WhatsApp |
| Devedor declarou pagamento | credor | confirmações | e-mail + WhatsApp |
| Seu pagamento foi confirmado | devedor | confirmações | e-mail |
| Seu comprovante foi rejeitado | devedor | confirmações | e-mail + WhatsApp |
| Proposta de compensação recebida | destinatário | confirmações | e-mail + WhatsApp |
| Compensação confirmada | proponente | confirmações | e-mail |
| Lembrete de parcela em aberto | devedor | lembretes | WhatsApp |

Nunca se notifica o que o próprio usuário fez (isso fica só no feed).

## Preferências (perfil)

Três interruptores por categoria no `User`: `notif_cobracas`,
`notif_confirmacoes`, `notif_lembretes` (padrão ligados). Se a categoria estiver
desligada, nada é enviado. WhatsApp só sai para telefone **verificado**; e-mail
sempre que houver endereço.

## Arquitetura

- `apps/notifications/service.py` — `notificar()`: aplica o gating e dispara nos
  canais. Assíncrono (thread daemon); nunca bloqueia a resposta nem propaga erro.
- `apps/notifications/events.py` — uma função por evento da matriz (mensagem + canais).
- `apps/notifications/channels.py` — e-mail (SMTP via Django) e WhatsApp (Twilio).
- Disparo pelos serviços via `transaction.on_commit` — só notifica se a transação
  confirmar (nada de aviso sobre algo que deu rollback).

### Configuração (produção)

```env
# E-mail (SMTP)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=...
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=Rachei <noreply@rachei.app>

# WhatsApp (Twilio)
WHATSAPP_BACKEND=apps.groups.whatsapp.TwilioWhatsAppBackend
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```

> WhatsApp Business exige **templates aprovados pela Meta** para mensagens
> iniciadas fora da janela de 24h. Cadastre os textos da matriz como templates
> antes de habilitar o envio real.

## Lembretes (comando idempotente + systemd timer)

O lembrete é o único envio **agendado**. A segurança contra duplicação vem da
**idempotência do comando**, não do agendador:

- envia quando a parcela está pendente, venceu há ≥ `LEMBRETE_APOS_DIAS` (padrão 3)
  e não recebeu lembrete nos últimos `LEMBRETE_INTERVALO_DIAS` (padrão 4);
- grava `ultimo_lembrete_em` na parcela — rodar 2× no mesmo dia **não** reenvia.

```bash
python manage.py enviar_lembretes            # envia
python manage.py enviar_lembretes --dry-run  # só relata
```

### Agendamento (systemd)

Arquivos em [`deploy/systemd/`](../deploy/systemd/):

```bash
sudo cp deploy/systemd/rachei-lembretes.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rachei-lembretes.timer

systemctl list-timers rachei-lembretes.timer   # confere o próximo disparo
journalctl -u rachei-lembretes -f               # acompanha os envios
```

`OnCalendar` no `.timer` controla o horário; `Persistent=true` recupera execuções
perdidas se o servidor estava desligado.

## Evolução

Os envios imediatos usam thread (sem retry se o Twilio/SMTP falhar) — aceitável
para o v1. Quando houver uma fila no projeto (ex.: Celery + Redis), os imediatos
ganham retry e o `Beat` substitui o systemd timer sem mudar o comando idempotente.
