# Rachei — Backend

API do **Rachei**, um app de divisão de contas entre amigos (estilo Splitwise):
grupos, dívidas, confirmação dupla de pagamento, compensação de saldos (netting),
2FA e notificações. Django REST Framework + PostgreSQL.

> Frontend (React + Vite) no repositório `rachei`.

## Stack

- **Django 6 + Django REST Framework**
- **PostgreSQL** (dev, CI e produção — sem SQLite)
- **JWT** (SimpleJWT) com refresh em cookie HttpOnly e rotação/blacklist
- **2FA/TOTP** (`pyotp`) com secret criptografado em repouso (Fernet)
- **Observabilidade**: Sentry + Better Stack (logs JSON), `/health`, request-id
- **Notificações**: e-mail (SMTP) e WhatsApp (Twilio)

## Estrutura

```
apps/
  users/       contas, login, 2FA, auditoria, verificação de telefone
  groups/      grupos, membros, convites/confirmação
  debts/       despesas e parcelas (divisão igual/personalizada)
  payments/    confirmação dupla, links de cobrança, acerto (compensação)
  notifications/ e-mail + WhatsApp por evento (respeita preferências)
  e2e/         seed/reset — só sob settings_e2e (testes full-stack)
config/        settings, settings_test, settings_e2e, urls, observability
tests/         suíte de segurança/autorização/regressão
```

Convenções detalhadas em [`CLAUDE.md`](CLAUDE.md) (models, serializers, segurança,
services, performance).

## Rodando localmente

Pré-requisitos: Python 3.12+ e um PostgreSQL local.

```bash
pip install -r requirements.txt

# .env (ver variáveis abaixo) — nunca commitar
# crie o banco:  createdb rachei
python manage.py migrate
python manage.py runserver           # http://localhost:8000
```

### Variáveis de ambiente (`.env`)

| Variável | Para quê |
|---|---|
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` | básico do Django |
| `CORS_ALLOWED_ORIGINS` | origem do frontend (ex.: http://localhost:5173) |
| `DB_ENGINE/DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT` | Postgres |
| `TOTP_ENCRYPTION_KEY` | chave Fernet do 2FA (obrigatória, sem fallback) |
| `EMAIL_*` / `DEFAULT_FROM_EMAIL` | notificações por e-mail (SMTP) |
| `SMS_BACKEND` / `WHATSAPP_BACKEND` / `TWILIO_*` | SMS/WhatsApp (Console em dev) |
| `SENTRY_DSN` / `BETTERSTACK_*` | observabilidade (opcional em dev) |

## Testes

```bash
# suíte completa (Postgres, hasher rápido)
python manage.py test --settings=config.settings_test

# um arquivo específico
python manage.py test tests.test_settle_up --settings=config.settings_test
```

- **~159 testes** de negócio, segurança e autorização; cobertura ≥ 80% (gate no CI).
- CI: GitHub Actions roda a suíte contra Postgres via Docker.
- Pre-push hook local: `git config core.hooksPath .githooks`.
- E2E full-stack (no repo `rachei`, com `settings_e2e`): ver `rachei/e2e/README.md`.

## Documentos

- [`CLAUDE.md`](CLAUDE.md) — convenções e padrões do código
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — roteiro de produção (VPS)
- [`docs/NOTIFICACOES.md`](docs/NOTIFICACOES.md) — matriz e infra de notificações
