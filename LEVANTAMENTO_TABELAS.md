# Levantamento de Tabelas — Rachei Backend

Análise baseada em `src/types/index.ts`, stores e páginas do frontend.
Todos os nomes em português. Prefixos únicos por tabela em `db_column`.

---

## Tabelas necessárias (8)

| # | Tabela              | App Django  | Situação          |
|---|---------------------|-------------|-------------------|
| 1 | `usuarios`          | `users`     | ⚠️ Incompleto     |
| 2 | `grupos`            | `groups`    | ⚠️ Incompleto     |
| 3 | `membros_grupo`     | `groups`    | ⚠️ Incompleto     |
| 4 | `despesas`          | `debts`     | ⚠️ Incompleto     |
| 5 | `parcelas`          | `debts`     | ⚠️ Incompleto     |
| 6 | `comprovantes`      | `payments`  | ❌ Não existe     |
| 7 | `links_cobranca`    | `payments`  | ⚠️ Incompleto     |
| 8 | `notificacoes_lidas`| `users`     | ❌ Não existe     |

> **Preferências de notificação** (3 toggles do ProfilePage) são 3 campos booleanos direto
> em `usuarios` — não justificam tabela separada para flags estáticas por usuário.

---

## Prefixos por tabela

| Tabela               | Prefixo |
|----------------------|---------|
| `usuarios`           | `usr_`  |
| `grupos`             | `grp_`  |
| `membros_grupo`      | `mgp_`  |
| `despesas`           | `dsp_`  |
| `parcelas`           | `pcl_`  |
| `comprovantes`       | `cpv_`  |
| `links_cobranca`     | `lnk_`  |
| `notificacoes_lidas` | `ntf_`  |

---

## 1. `usuarios` — ⚠️ Incompleto

Mapeado de: `User` (types/index.ts) + toggles do ProfilePage.

**Campos faltantes:**

| Campo Django              | Tipo                        | Obs                               |
|---------------------------|-----------------------------|-----------------------------------|
| `phone`                   | `CharField(20, blank=True)` | Opcional                          |
| `avatar_url`              | `URLField(blank=True)`      | Foto de perfil                    |
| `notif_cobracas`          | `BooleanField(default=True)`| Toggle "Cobranças recebidas"      |
| `notif_confirmacoes`      | `BooleanField(default=True)`| Toggle "Confirmações de pagamento"|
| `notif_lembretes`         | `BooleanField(default=True)`| Toggle "Lembretes semanais"       |

`name` do frontend = `first_name + last_name` do AbstractUser — sem campo extra.

**Meta:**
```python
class Meta:
    db_table = 'usuarios'
```

---

## 2. `grupos` — ⚠️ Incompleto

Mapeado de: `Group` (types/index.ts).

**Campos faltantes:**

| Campo Django | Tipo                    | Obs                   |
|--------------|-------------------------|-----------------------|
| `archived`   | `BooleanField(False)`   | Soft-delete de grupos |

**Meta:**
```python
class Meta:
    db_table = 'grupos'
```

---

## 3. `membros_grupo` — ⚠️ Incompleto

Mapeado de: `GroupMember` (types/index.ts).

**Campos faltantes:**

| Campo Django | Tipo                              | Obs                          |
|--------------|-----------------------------------|------------------------------|
| `role`       | `CharField(choices=ROLE_CHOICES)` | `admin` ou `member`          |

**Meta:**
```python
class Meta:
    db_table = 'membros_grupo'
    unique_together = ('group', 'user')
```

---

## 4. `despesas` — ⚠️ Incompleto

Mapeado de: `Debt` (types/index.ts).

**Campos faltantes:**

| Campo Django | Tipo               | Obs                                              |
|--------------|--------------------|--------------------------------------------------|
| `created_by` | `ForeignKey(User)` | Quem registrou (pode diferir de `paid_by`)       |

**Meta:**
```python
class Meta:
    db_table = 'despesas'
    ordering = ['-created_at']
```

---

## 5. `parcelas` — ⚠️ Incompleto

Mapeado de: `Installment` (types/index.ts).

**Ação necessária:**

| Ação   | Campo      | Motivo                                                      |
|--------|------------|-------------------------------------------------------------|
| Remover | `proof_url` | O frontend trata `PaymentProof` como entidade separada → tabela `comprovantes` |

**Meta:**
```python
class Meta:
    db_table = 'parcelas'
```

---

## 6. `comprovantes` — ❌ Não existe

Mapeado de: `PaymentProof` (types/index.ts).
Tabela separada permite múltiplas tentativas e auditoria de quem enviou.

| Campo Django   | Tipo                        | Obs                           |
|----------------|-----------------------------|-------------------------------|
| `id`           | `UUIDField(PK)`             |                               |
| `parcela`      | `ForeignKey(Installment)`   | Relacionamento com a parcela  |
| `file_url`     | `URLField`                  | URL do arquivo no storage     |
| `uploaded_at`  | `DateTimeField(auto_now_add)`|                              |
| `uploaded_by`  | `ForeignKey(User)`          | Rastreabilidade               |

**Meta:**
```python
class Meta:
    db_table = 'comprovantes'
```

---

## 7. `links_cobranca` — ⚠️ Incompleto

Mapeado de: `ChargeLink` (types/index.ts).

**Campos faltantes:**

| Campo Django | Tipo                  | Obs                                  |
|--------------|-----------------------|--------------------------------------|
| `used_at`    | `DateTimeField(null)` | Quando o link foi acessado           |

**Meta:**
```python
class Meta:
    db_table = 'links_cobranca'
```

---

## 8. `notificacoes_lidas` — ❌ Não existe

`readEventIds: Set<string>` está em localStorage no frontend.
No backend, persiste por usuário para sincronizar entre dispositivos.

Os IDs de evento são strings derivadas (não há tabela de eventos), seguindo o padrão:
- `ev-created-{despesaId}`
- `ev-added-{despesaId}`
- `ev-proof-{parcelaId}`
- `ev-paid-{parcelaId}`
- `ev-mypaid-{parcelaId}`
- `ev-pending-{parcelaId}`
- `ev-charged-{parcelaId}`

| Campo Django | Tipo                          | Obs                                     |
|--------------|-------------------------------|-----------------------------------------|
| `id`         | `BigAutoField`                | PK simples — UUID desnecessário aqui    |
| `usuario`    | `ForeignKey(User)`            | Quem leu                                |
| `evento_id`  | `CharField(60)`               | String derivada, ex: `ev-proof-abc123`  |
| `lida_em`    | `DateTimeField(auto_now_add)` |                                         |

Índice único em `(usuario, evento_id)`.

**Meta:**
```python
class Meta:
    db_table = 'notificacoes_lidas'
    unique_together = ('usuario', 'evento_id')
```

---

## Diagrama de relacionamentos

```
usuarios ────────────────────────────────────────────────────────┐
  │                                                              │
  │ paid_by / created_by                                         │
  ▼                                                              │
despesas ──── membros_grupo ──── grupos                          │
  │                │                                            │
  ▼                └── usuario ──────────────────────────────────┘
parcelas
  │    │
  │    └──── comprovantes (uploaded_by → usuarios)
  │
  └──────── links_cobranca (OneToOne)

usuarios ──── notificacoes_lidas
```

---

## Resumo das ações

| # | Ação                   | Tabela               | Detalhe                                    |
|---|------------------------|----------------------|--------------------------------------------|
| 1 | Renomear + atualizar   | `usuarios`           | `db_table`, prefixos, + 5 campos novos     |
| 2 | Renomear + atualizar   | `grupos`             | `db_table`, prefixos, + `archived`         |
| 3 | Renomear + atualizar   | `membros_grupo`      | `db_table`, prefixos, + `role`             |
| 4 | Renomear + atualizar   | `despesas`           | `db_table`, prefixos, + `created_by`       |
| 5 | Renomear + atualizar   | `parcelas`           | `db_table`, prefixos, remover `proof_url`  |
| 6 | Criar                  | `comprovantes`       | Tabela nova com 5 campos                   |
| 7 | Renomear + atualizar   | `links_cobranca`     | `db_table`, prefixos, + `used_at`          |
| 8 | Criar                  | `notificacoes_lidas` | Tabela nova com índice único               |
