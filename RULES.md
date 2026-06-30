# Regras e Boas Práticas — Rachei Backend

## 1. Nomenclatura de Campos (prefixos por tabela)

Cada tabela usa um prefixo de 3 letras em todos os seus campos via `db_column`.
O nome Python segue o padrão Django (sem prefixo), mas a coluna no banco é prefixada.
Isso evita ambiguidade em JOINs e facilita debugging direto no SQL.

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

**Exemplo:**

```python
class Despesa(models.Model):
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column='dsp_id')
    description     = models.CharField(max_length=255, db_column='dsp_descricao')
    total_amount_cents = models.PositiveIntegerField(db_column='dsp_total_centavos')
    split_type      = models.CharField(..., db_column='dsp_tipo_divisao')
    created_at      = models.DateTimeField(auto_now_add=True, db_column='dsp_criado_em')
```

---

## 2. Serializers — uma classe por intenção

Nunca usar `fields = '__all__'`. Nunca reutilizar o mesmo serializer para list, detail e form.

| Sufixo             | Uso                                              |
|--------------------|--------------------------------------------------|
| `XxxListSerializer`   | Campos mínimos para listagens (grid/tabela)   |
| `XxxDetailSerializer` | Campos completos para tela de detalhe         |
| `XxxFormSerializer`   | Validação e escrita (create / update)         |

**Exemplo:**

```python
class DespesaListSerializer(serializers.ModelSerializer):
    """Usado em GET /api/grupos/:id/despesas/ — dados mínimos para o card."""
    class Meta:
        model = Despesa
        fields = ('id', 'description', 'total_amount_cents', 'split_type', 'created_at')


class DespesaDetailSerializer(serializers.ModelSerializer):
    """Usado em GET /api/despesas/:id/ — inclui parcelas aninhadas."""
    parcelas = ParcelaListSerializer(many=True, read_only=True)

    class Meta:
        model = Despesa
        fields = ('id', 'description', 'total_amount_cents', 'split_type', 'created_at', 'paid_by', 'parcelas')


class DespesaFormSerializer(serializers.ModelSerializer):
    """Usado em POST /api/despesas/ — valida entrada, nunca expõe campos internos."""
    class Meta:
        model = Despesa
        fields = ('grupo', 'description', 'total_amount_cents', 'split_type')
```

---

## 3. Valores Monetários

- **Sempre inteiros em centavos.** Nunca `DecimalField` ou `FloatField` para dinheiro.
- O campo deve terminar em `_cents`: `total_amount_cents`, `amount_cents`.
- A conversão para reais acontece apenas na camada de apresentação (frontend).

---

## 4. Segurança

### 4.1 Autenticação e permissões
- `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]` no settings — toda rota é protegida por padrão.
- Rotas públicas (ex: resolver charge link) devem declarar `permission_classes = [AllowAny]` explicitamente na view.
- Nunca usar `permission_classes = []` — sempre passar `[AllowAny]` para deixar a intenção clara.

### 4.2 Variáveis de ambiente
- `SECRET_KEY`, `DATABASE_URL`, credenciais de serviços externos: sempre via `.env`, nunca hardcoded.
- `.env` no `.gitignore`. `.env.example` commitado sem valores reais.

### 4.3 Exposição de dados
- Serializers de listagem nunca retornam campos sensíveis (`password_hash`, tokens, `proof_url` completa).
- Nunca expor PKs inteiros sequenciais na API — usar UUID.
- Campos `write_only=True` em senhas e tokens nos serializers de form.

### 4.4 Validação
- Toda validação de negócio fica no `validate()` ou `validate_<field>()` do serializer, não na view.
- Nunca confiar em dados do cliente para definir `paid_by`, `created_by` — sempre usar `request.user`.

```python
def perform_create(self, serializer):
    serializer.save(paid_by=self.request.user)
```

### 4.5 Queries brutas
- Nunca usar `raw()` ou `cursor.execute()` com input do usuário sem parâmetros preparados.
- Preferir sempre o ORM do Django.

---

## 5. Performance e Otimização

### 5.1 Evitar N+1 — sempre
- `select_related()` para ForeignKey e OneToOne.
- `prefetch_related()` para ManyToMany e relacionamentos reversos.
- Toda view de listagem deve ter o queryset otimizado antes de chegar no serializer.

```python
# Ruim — dispara 1 query por debt
queryset = Debt.objects.filter(group=group)

# Certo
queryset = (
    Debt.objects
    .filter(group=group)
    .select_related('paid_by')
    .prefetch_related('installments__debtor')
)
```

### 5.2 Limitar campos retornados
- Usar `only()` quando o serializer usa apenas alguns campos do model.
- Nunca buscar colunas que não serão usadas.

### 5.3 Paginação obrigatória em listagens
- Todo endpoint de lista usa `PageNumberPagination` com `page_size` máximo definido.
- Nunca retornar um queryset sem paginar.

```python
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}
```

### 5.4 Índices
- Campos usados em `.filter()` frequente devem ter `db_index=True`.
- ForeignKeys já indexam automaticamente; revisar campos como `status`, `created_at`.

### 5.5 `exists()` em vez de `count()`
```python
# Ruim
if qs.count() > 0:

# Certo
if qs.exists():
```

---

## 6. Views — usar ViewSets

- Usar `ModelViewSet` ou `GenericViewSet` com mixins explícitos.
- Lógica de negócio vai em `perform_create`, `perform_update`, ou em um `service.py` por app.
- Views só orquestram: pegam dados, chamam serviço, devolvem resposta.

```
users/
  views.py       ← ViewSets finos
  serializers.py ← List / Detail / Form
  services.py    ← regras de negócio
  urls.py
```

---

## 7. Migrations

- Toda migration gerada com `python manage.py makemigrations <app>` — nunca `makemigrations` geral em produção.
- Nunca editar migration já aplicada em produção.
- Migrations de dados (data migrations) usam `RunPython` com função de rollback definida.
- Revisar o SQL gerado com `sqlmigrate` antes de aplicar em produção.

---

## 8. Testes

- Cada app tem `tests/` com arquivos separados: `test_models.py`, `test_serializers.py`, `test_views.py`.
- Usar `APITestCase` do DRF para testar endpoints.
- Banco de testes usa fixtures ou `setUp` com `baker` / `factory_boy` — nunca fixtures JSON manuais.
- Coverage mínimo de 80% nos apps de negócio (`debts`, `groups`, `payments`).
