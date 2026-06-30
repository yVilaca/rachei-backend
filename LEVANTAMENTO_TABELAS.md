# Levantamento de Tabelas — Rachei Backend

Mapeamento completo baseado em `src/types/index.ts`, `mock-data.ts` e stores do frontend.
Indica o que já existe no modelo atual, o que está incompleto e o que está faltando.

---

## Status geral dos modelos atuais

| Tabela              | Situação          |
|---------------------|-------------------|
| `users`             | ⚠️ Incompleto     |
| `groups`            | ⚠️ Incompleto     |
| `group_members`     | ⚠️ Incompleto     |
| `debts`             | ⚠️ Incompleto     |
| `installments`      | ⚠️ Incompleto     |
| `payment_proofs`    | ❌ Não existe     |
| `charge_links`      | ⚠️ Incompleto     |
| `event_reads`       | ❌ Não existe     |

---

## 1. `users` — ⚠️ Incompleto

Campos que existem no frontend (`User`) e estão **faltando** no model:

| Campo frontend | Campo Django    | Tipo                  | Obs                              |
|----------------|------------------|-----------------------|----------------------------------|
| `phone`        | `phone`          | `CharField(20, blank)` | Opcional                        |
| `avatarUrl`    | `avatar_url`     | `URLField(blank)`     | Foto de perfil                   |

O `name` do frontend é `first_name + last_name` do AbstractUser — não precisa de campo extra.

---

## 2. `groups` — ⚠️ Incompleto

Campo presente no frontend e **ausente** no model:

| Campo frontend | Campo Django | Tipo                   | Obs                       |
|----------------|--------------|------------------------|---------------------------|
| `archived`     | `archived`   | `BooleanField(False)`  | Soft-delete de grupos     |

---

## 3. `group_members` — ⚠️ Incompleto

Campo presente no frontend e **ausente** no model:

| Campo frontend | Campo Django | Tipo                          | Obs                             |
|----------------|--------------|-------------------------------|---------------------------------|
| `role`         | `role`       | `CharField(choices=admin/member)` | Controle de permissão no grupo |

---

## 4. `debts` — ⚠️ Incompleto

Campo presente no frontend e **ausente** no model:

| Campo frontend | Campo Django  | Tipo                | Obs                                               |
|----------------|---------------|---------------------|---------------------------------------------------|
| `createdBy`    | `created_by`  | `ForeignKey(User)`  | Quem registrou (pode diferir de `paid_by` no futuro) |

---

## 5. `installments` — ⚠️ Incompleto

O model atual tem `proof_url: URLField` inline, mas o frontend trata `PaymentProof` como **entidade própria**. Além disso, falta o campo de rastreio de quem enviou o comprovante.

Campos a **remover** do model atual:
- `proof_url` — vai para a tabela `payment_proofs`

---

## 6. `payment_proofs` — ❌ Não existe

Entidade separada no frontend (`PaymentProof`). Deve ser tabela própria para permitir múltiplas tentativas e auditoria.

| Campo frontend   | Campo Django    | Tipo               | Obs                              |
|------------------|-----------------|--------------------|----------------------------------|
| `id`             | `id`            | `UUIDField(PK)`    |                                  |
| `installmentId`  | `installment`   | `ForeignKey(Installment)` | Um por installment por vez (OneToOne por status) |
| `fileUrl`        | `file_url`      | `URLField`         | URL do arquivo no storage        |
| `uploadedAt`     | `uploaded_at`   | `DateTimeField(auto_now_add)` |                        |
| *(ausente)*      | `uploaded_by`   | `ForeignKey(User)` | Quem enviou (rastreabilidade)    |

---

## 7. `charge_links` — ⚠️ Incompleto

Campo presente no frontend e **ausente** no model:

| Campo frontend | Campo Django | Tipo                    | Obs                                     |
|----------------|--------------|-------------------------|-----------------------------------------|
| `usedAt`       | `used_at`    | `DateTimeField(null)`   | Registra quando o link foi acessado     |

---

## 8. `event_reads` — ❌ Não existe

No frontend, `readEventIds: Set<string>` é persistido em localStorage.
No backend, esse estado precisa ser persistido por usuário para sincronizar entre dispositivos.

Os IDs de evento são derivados (não existem como registros), seguindo o padrão:
- `ev-created-{debtId}`
- `ev-added-{debtId}`
- `ev-proof-{installmentId}`
- `ev-paid-{installmentId}`
- `ev-mypaid-{installmentId}`
- `ev-pending-{installmentId}`
- `ev-charged-{installmentId}`

| Campo      | Tipo                | Obs                                          |
|------------|---------------------|----------------------------------------------|
| `id`       | `BigAutoField`      | PK simples (não precisa de UUID)             |
| `user`     | `ForeignKey(User)`  | Quem leu                                     |
| `event_id` | `CharField(60)`     | String derivada, ex: `ev-proof-inst-abc123`  |
| `read_at`  | `DateTimeField(auto_now_add)` |                                    |

Índice único em `(user, event_id)`.

---

## Prefixos por tabela (conforme RULES.md)

| Tabela             | Prefixo |
|--------------------|---------|
| `users`            | `usr_`  |
| `groups`           | `grp_`  |
| `group_members`    | `grm_`  |
| `debts`            | `dbt_`  |
| `installments`     | `ins_`  |
| `payment_proofs`   | `prf_`  |
| `charge_links`     | `chl_`  |
| `event_reads`      | `evr_`  |

---

## Diagrama de relacionamentos

```
users ────────────────────────────────────────────────────┐
  │                                                        │
  │ created_by / paid_by                                   │
  ▼                                                        │
debts ──────── group_members ──── groups                   │
  │                    │                                   │
  ▼                    └── user ──────────────────────────-┘
installments
  │    │
  │    └──── payment_proofs (OneToOne por comprovante ativo)
  │
  └──────── charge_links (OneToOne)

users ──── event_reads (leituras de notificação)
```

---

## Resumo das ações necessárias

1. **Atualizar `users`** — adicionar `phone`, `avatar_url`
2. **Atualizar `groups`** — adicionar `archived`
3. **Atualizar `group_members`** — adicionar `role`
4. **Atualizar `debts`** — adicionar `created_by`
5. **Atualizar `installments`** — remover `proof_url` inline
6. **Criar `payment_proofs`** — tabela nova com `uploaded_by`
7. **Atualizar `charge_links`** — adicionar `used_at`
8. **Criar `event_reads`** — tabela nova com índice `(user, event_id)`
9. **Aplicar `db_column` com prefixos** em todos os campos de todas as tabelas
