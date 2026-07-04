# Rachei Backend — Instruções para Claude

Exemplos de código detalhados em `.claude/rules/`.

---

## Models

- Modelo de negócio: PK `UUIDField` com `db_column='xxx_id'`
- Tabela de junção simples: PK `BigAutoField` com `db_column` explícito
- `db_table` sempre em português
- Todo campo tem `db_column` com prefixo de 3 letras (incluindo a PK)
- `db_index=True` em campos de filtro frequente (`status`, `archived`)
- Status com valores ativos como minoria: índice parcial via `Meta.indexes` com `condition=Q(...)`

| Tabela               | Prefixo | Tabela               | Prefixo |
|----------------------|---------|----------------------|---------|
| `usuarios`           | `usr_`  | `comprovantes`       | `cpv_`  |
| `grupos`             | `grp_`  | `links_cobranca`     | `lnk_`  |
| `membros_grupo`      | `mgp_`  | `notificacoes_lidas` | `ntf_`  |
| `despesas`           | `dsp_`  | | |
| `parcelas`           | `pcl_`  | | |

---

## Valores Monetários

- Sempre inteiros em centavos — nunca `float` ou `Decimal`
- Nome do campo termina em `_cents`: `total_amount_cents`, `amount_cents`
- Divisão inteira distribui centavos restantes entre os primeiros N devedores (soma sempre exata)
- Conversão para reais somente no frontend

---

## Serializers

- Nunca `fields = '__all__'` — nunca reutilizar o mesmo serializer para propósitos diferentes
- `XxxListSerializer` — campos mínimos para cards/grids
- `XxxDetailSerializer` — campos completos para tela de detalhe
- `XxxFormSerializer` — validação e escrita (create/update)
- Validação de negócio em `validate()` ou `validate_<field>()`, nunca na view
- `SerializerMethodField` que acessa relação exige `prefetch_related` declarado na view — nunca disparar query dentro do serializer

---

## Segurança

- `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]` — toda rota protegida por padrão
- Rotas públicas: `permission_classes = [AllowAny]` explícito na view — nunca `[]`
- `paid_by`, `created_by`, `uploaded_by` sempre de `request.user`, nunca do corpo da requisição
- Toda config que varia por ambiente via `os.getenv()` — nunca hardcoded
- Nunca expor PKs inteiros sequenciais — usar UUID
- Nunca `raw()` ou `cursor.execute()` com input do usuário sem parâmetros preparados

---

## Services

- Lógica com mais de um model ou operação fica em `services.py`, nunca na view
- Funções usam apenas argumentos nomeados (`def f(*, a, b):`)
- Services levantam exceções stdlib (`ValueError`, `PermissionError`) — nunca DRF
- A view converte: `PermissionError` → `PermissionDenied` / `ValueError` → `ValidationError`
- Multi-escrita: `@transaction.atomic`
- Atualização de status: `.update()` no banco — nunca `.save()` em instância carregada
- Inserção em lote: `bulk_create()` — nunca loop de `.create()`
- Operações idempotentes: `bulk_create(ignore_conflicts=True)`

---

## Querysets e Performance

- `select_related()` para FK/OneToOne acessados no serializer
- `prefetch_related()` para relações reversas e M2M — toda view de listagem já otimizada
- Nunca `.filter(relacao__campo=x).distinct()` — usar subquery `__in`
- `Count('campo')` após `filter()` na mesma relação: sempre `Count('campo', distinct=True)`
- `Prefetch(queryset=Model.objects.order_by(...))` em vez de `sorted()` em Python
- Verificar que **o mesmo membro** satisfaz duas condições: único `.filter(a=x, b=y)`, não dois `.filter()` encadeados
- Resultado de lookup repetido na mesma view: cachear em `self._attr` com `hasattr`
- `CONN_MAX_AGE` via env var — `0` para SQLite dev, `60` para PostgreSQL produção
- `exists()` para checar presença — nunca `count() > 0`

---

## Exceções e Código

- Nunca `except Exception` — capturar sempre o tipo específico esperado
- Para OneToOne reverso ausente: `except ObjectDoesNotExist` (evita import circular)
- Todos os imports no topo do arquivo — nunca dentro de funções ou métodos
- Variáveis atribuídas e nunca usadas: remover imediatamente

---

## Views

- Views só orquestram: recebem dados, chamam service, devolvem resposta
- Invariantes de negócio (ex: último admin do grupo) validadas na view ou service com erro explícito
- Helpers de acesso (ex: `_get_grupo`) fazem verificação em uma única query combinada

---

## Migrations

- `makemigrations <app>` — nunca `makemigrations` geral em produção
- Nunca editar migration já aplicada em produção
- Revisar com `sqlmigrate` antes de aplicar em produção
- Migrations de dados com credenciais: chave em `os.environ.get('VAR')` sem default — no-op se ausente (seguro em CI)
- Contar e logar: processados, pulados e motivo de cada skip — nenhuma linha falha silenciosamente
- Erro em qualquer linha: `raise RuntimeError(...)` para reverter a transação inteira
- Exceções específicas: nunca `except Exception` — capturar `InvalidToken`, `binascii.Error`, `UnicodeDecodeError` separadamente

---

## M2F — Autenticação de Dois Fatores

Sistema completo em `apps/users/`. Não reimplementar; estender sobre o que existe.

- **TOTP**: `pyotp` + `EncryptedCharField` (Fernet) — secret at-rest; chave via `TOTP_ENCRYPTION_KEY` (sem fallback)
- **Anti-replay**: `exclude(last_otp_counter=counter).update(...)` — 0 rows = replay; sem lock explícito
- **Rate limiting**: `otp_fail_count` + `otp_locked_until` por config (5 falhas → 5 min, 10 → 1 hora)
- **Trusted devices**: token SHA-256, validade 30 dias, revogáveis via `DELETE /api/auth/2fa/trusted-devices/<id>/`
- **`TwoFAPendingToken`**: `type='2fa_pending'`, 15 min, rejeitado em rotas que exigem `type='access'`
- **Blacklist**: ativar E desativar 2FA invalida todos os `OutstandingToken` com `bulk_create(ignore_conflicts=True)`

### Testes — isolamento obrigatório

- `@override_settings(TOTP_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)` em toda classe que instancia `TwoFactorConfig`
- `cache.clear()` no `setUp` de toda classe com endpoints que usam `AuthRateThrottle`
- Testes com threading: `TransactionTestCase` (não `TestCase`) — `TestCase` não comita; threads não vêem o banco
- Testar lógica de migration diretamente: `importlib.import_module('apps.users.migrations.0009_...')` + `mock_editor.connection = connection`
