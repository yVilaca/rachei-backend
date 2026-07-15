# Roteiro de deploy / migração para VPS

Checklist do que fazer quando sair do dev local para uma VPS de produção.
Nada aqui roda sozinho hoje — é o guia + os templates prontos (`docker-compose.prod.yml`
e `.github/workflows/deploy.yml.example`).

---

## Visão geral do fluxo

```
git push (master)
      │
      ▼
CI (GitHub Actions) roda os testes  ──❌──> para aqui (não faz deploy)
      │ ✅
      ▼
Deploy: build da imagem Docker → push pro registry (ghcr.io)
      │
      ▼
VPS: puxa a imagem → aplica migrations → reinicia (docker compose up -d)
      │
      ▼
Smoke test: GET /health/ == 200  ──❌──> alerta / rollback
      │ ✅
      ▼
Sentry: marca a release (SHA) + sobe source maps do frontend
```

Regra de ouro: **deploy só depois da CI verde**. É isso que garante que uma
publicação não quebra o que já funcionava.

---

## 1. Preparar a VPS (uma vez)

- [ ] Criar a VPS (Ubuntu LTS recomendado) e um usuário não-root com sudo.
- [ ] Instalar **Docker** + **docker compose**.
- [ ] Firewall: liberar 80/443 (web) e 22 (SSH); **fechar 5432** (Postgres não fica exposto).
- [ ] Apontar seu **domínio** (registro A) para o IP da VPS.
- [ ] Criar a pasta do projeto: `/opt/rachei` (vai conter `docker-compose.prod.yml` e `.env.prod`).

## 2. Banco de dados (Postgres)

Duas opções:
- **No compose** (mais simples): o `docker-compose.prod.yml` já sobe um Postgres com volume persistente.
- **Gerenciado** (mais robusto: backup automático): um Postgres da Neon/Supabase/RDS. Nesse caso, remova o serviço `db` do compose e aponte as `DB_*` para o host gerenciado.

- [ ] Definir `DB_NAME`, `DB_USER`, `DB_PASSWORD` **fortes** (nada de `root`).
- [ ] Garantir backup (dump agendado ou o backup do serviço gerenciado).

## 3. Segredos e variáveis (nunca no git)

- [ ] Criar `/opt/rachei/.env.prod` na VPS com os valores reais:
  - `SECRET_KEY` (novo, forte), `DEBUG=False`, `ALLOWED_HOSTS=seu-dominio.com`
  - `CORS_ALLOWED_ORIGINS=https://seu-dominio.com`
  - `DB_ENGINE/DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT`
  - `TOTP_ENCRYPTION_KEY` (a chave Fernet de produção)
  - `SENTRY_DSN`, `SENTRY_ENVIRONMENT=production`, `SENTRY_TRACES_SAMPLE_RATE=0.1`
  - `BETTERSTACK_SOURCE_TOKEN`, `BETTERSTACK_HOST`
  - `NUM_PROXIES=1` (atrás do nginx — para o rate limit ler o IP real)
- [ ] Cadastrar os **secrets no GitHub** (Settings → Secrets and variables → Actions):
  - `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `APP_DOMAIN`
  - `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT` (source maps/release)

## 4. HTTPS / reverse proxy

- [ ] Subir **nginx** (ou Caddy) na frente: recebe 443, encaminha para o `web:8000`.
- [ ] TLS automático via **Let's Encrypt** (Caddy faz sozinho; nginx via certbot).
- [ ] Servir o **frontend** (build estático) e mandar `/api` e `/health` para o backend.

## 5. Ativar o pipeline de deploy

- [ ] Renomear `.github/workflows/deploy.yml.example` → `deploy.yml`.
- [ ] Conferir a imagem no compose (`ghcr.io/SEU_USUARIO/rachei-backend`).
- [ ] Colocar `docker-compose.prod.yml` em `/opt/rachei` na VPS.
- [ ] Rodar o deploy manualmente a 1ª vez (Actions → Deploy → Run workflow) e validar.
- [ ] (Opcional) Trocar para deploy automático após CI verde (bloco `workflow_run` comentado no template).

## 6. Observabilidade em produção

- [ ] **Sentry**: com `SENTRY_ENVIRONMENT=production` e `release=SHA`, os erros passam a ser atribuíveis a cada deploy.
- [ ] **Source maps** do frontend: subir no build de deploy (secrets `SENTRY_*`) → stack traces legíveis.
- [ ] **Better Stack Uptime**: criar monitor apontando para `https://seu-dominio.com/health/` (espera 200) + página de status.
- [ ] **Alertas**: e-mail/Slack para queda no uptime e pico de `login_fail` (segurança).

## 7. Pós-deploy e rollback

- [ ] Smoke test do `/health` já roda no pipeline (falhou → deploy falha).
- [ ] **Rollback**: como cada imagem tem a tag do SHA, reverter é subir a tag anterior
      (`docker compose` apontando para `:SHA_ANTERIOR` e `up -d`).

## 8. Frontend (build estático)

O frontend não é um servidor: é um monte de arquivos estáticos.
- [ ] Build: `pnpm build` (na CI/deploy), com `VITE_API_URL=https://seu-dominio.com` e `VITE_SENTRY_*`.
- [ ] Publicar o `dist/`: servido pelo nginx da VPS **ou** por um host estático (Vercel/Netlify/Cloudflare Pages).
- [ ] Subir os **source maps** ao Sentry no build (plugin já configurado, ativa com `SENTRY_AUTH_TOKEN`).

## 9. Depois: migrar o driver para Jenkins (opcional)

O núcleo do deploy é **Docker** (`Dockerfile` + `docker-compose.prod.yml`). Trocar
o GitHub Actions por Jenkins é só reescrever "quem chama" — os mesmos comandos
(`build`, `push`, `compose pull/up`, smoke test) viram estágios de um `Jenkinsfile`.
Nenhum retrabalho na aplicação.
