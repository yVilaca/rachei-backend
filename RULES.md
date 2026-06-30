# Regras e Boas Práticas — Rachei Backend

---

## 1. Models

### 1.1 Chaves primárias
- Modelos de negócio usam `UUIDField` como PK: `id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column='xxx_id')`.
- Tabelas de junção e metadados simples (sem necessidade de referência externa) usam `BigAutoField` com `db_column` explícito.

### 1.2 Nomes de tabelas
- Toda tabela tem `db_table` definida em português na classe `Meta`.
- O nome Python da classe pode ser em inglês; o nome no banco é sempre em português.

### 1.3 Prefixos de campo (`db_column`)
Cada tabela usa um prefixo de 3 letras em **todos** os campos via `db_column`, incluindo a PK. Isso elimina ambiguidade em JOINs e facilita leitura direta do SQL.

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

```python
# Exemplo completo
class Installment(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column='pcl_id')
    debt       = models.ForeignKey(Debt, db_column='pcl_despesa_id', ...)
    amount_cents = models.PositiveIntegerField(db_column='pcl_valor_centavos')
    status     = models.CharField(db_column='pcl_status', db_index=True, ...)

    class Meta:
        db_table = 'parcelas'
```

### 1.4 Índices
- `db_index=True` em campos usados frequentemente em `.filter()`: `status`, `archived` e similares.
- Campos de status com conjunto limitado de valores e maioria dos registros num subconjunto (ex: parcelas pagas) devem usar **índice parcial** via `Meta.indexes`:

```python
class Meta:
    db_table = 'parcelas'
    indexes = [
        models.Index(
            fields=['status'],
            name='pcl_status_ativo_idx',
            condition=models.Q(status__in=['pending', 'awaiting_confirmation']),
        ),
    ]
```

---

## 2. Valores Monetários

- **Sempre inteiros em centavos.** Nunca `DecimalField` ou `FloatField` para dinheiro.
- O nome do campo sempre termina em `_cents`: `total_amount_cents`, `amount_cents`.
- Divisão em partes iguais distribui o centavo restante entre os primeiros N devedores — a soma de todas as parcelas deve ser sempre exatamente igual ao total.
- A conversão para reais acontece **apenas** na camada de apresentação (frontend).

```python
n = len(debtors)
base = total_cents // n
remainder = total_cents % n
amounts = [base + (1 if i < remainder else 0) for i in range(n)]
```

---

## 3. Serializers — uma classe por intenção

Nunca usar `fields = '__all__'`. Nunca reutilizar o mesmo serializer para list, detail e form.

| Sufixo                  | Uso                                            |
|-------------------------|------------------------------------------------|
| `XxxListSerializer`     | Campos mínimos para listagens (grid/card)      |
| `XxxDetailSerializer`   | Campos completos para tela de detalhe          |
| `XxxFormSerializer`     | Validação e escrita (create / update)          |

- Campos `write_only=True` em senhas e tokens nos serializers de form.
- Validação de negócio fica em `validate()` ou `validate_<field>()` do serializer, nunca na view.
- `SerializerMethodField` que acessa relações requer que o queryset correspondente tenha `prefetch_related` declarado na view — nunca disparar query dentro do serializer.

---

## 4. Segurança

### 4.1 Autenticação e permissões
- `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]` no settings — toda rota é protegida por padrão.
- Rotas públicas declaram `permission_classes = [AllowAny]` explicitamente na view.
- Nunca usar `permission_classes = []` — sempre passar `[AllowAny]` para deixar a intenção clara.

### 4.2 Variáveis de ambiente
- `SECRET_KEY`, credenciais de banco e serviços externos: sempre via `.env`, nunca hardcoded.
- `.env` no `.gitignore`. `.env.example` commitado sem valores reais.
- Toda configuração que varia por ambiente (DB engine, CONN_MAX_AGE, CORS) vem de `os.getenv()`.

### 4.3 Exposição de dados
- Serializers de listagem nunca retornam campos sensíveis.
- Nunca expor PKs inteiros sequenciais na API — usar UUID.
- Endpoints públicos (ex: link de cobrança) expõem apenas os campos necessários para aquela tela — sem tokens, sem emails de outros usuários.

### 4.4 Campos preenchidos pelo servidor
- `paid_by`, `created_by`, `uploaded_by` e equivalentes **sempre** vêm de `request.user`, nunca do corpo da requisição.
- Nunca confiar no cliente para definir o autor de uma ação.

```python
def perform_create(self, serializer):
    serializer.save(created_by=self.request.user)
```

### 4.5 Queries brutas
- Nunca usar `raw()` ou `cursor.execute()` com input do usuário sem parâmetros preparados.
- Preferir sempre o ORM do Django.

---

## 5. Services

- Lógica de negócio que envolve mais de um model ou mais de uma operação fica em `services.py`, nunca na view.
- Funções de serviço usam apenas argumentos nomeados (`*`) para evitar erros de posição.
- Services levantam exceções da stdlib (`ValueError`, `PermissionError`) — nunca exceções do DRF. A view converte:

```python
# service
def criar_despesa(*, grupo, paid_by, ...):
    if paid_by.pk not in member_ids:
        raise PermissionError('Você não é membro deste grupo.')

# view
try:
    criar_despesa(...)
except PermissionError as e:
    raise PermissionDenied(str(e))
except ValueError as e:
    raise ValidationError(str(e))
```

### 5.1 Operações atômicas
- Todo serviço que faz mais de uma escrita usa `@transaction.atomic`.
- Toda alteração de status usa `.update()` direto no banco, não `.save()` numa instância carregada:

```python
# Ruim — sobrescreve outros campos modificados concorrentemente
parcela.status = 'paid'
parcela.save()

# Certo — atomic, altera só o que deve
Installment.objects.filter(pk=parcela.pk).update(
    status='paid',
    paid_at=timezone.now(),
)
```

### 5.2 Operações em lote
- Inserções múltiplas usam `bulk_create()` — nunca um loop de `.create()`.
- Para operações idempotentes (ex: marcar notificações como lidas), usar `bulk_create(ignore_conflicts=True)`.

```python
Installment.objects.bulk_create([
    Installment(debt=despesa, debtor=p['debtor'], amount_cents=p['amount_cents'])
    for p in parcelas_data
])
```

---

## 6. Performance e Querysets

### 6.1 Evitar N+1 — obrigatório
- `select_related()` para ForeignKey e OneToOne acessados no serializer.
- `prefetch_related()` para ManyToMany e relacionamentos reversos.
- Todo queryset de listagem tem os prefetches declarados na view antes de chegar no serializer.

### 6.2 Subquery em vez de JOIN + DISTINCT
- Nunca usar `.filter(relacao__campo=valor).distinct()` — gera `SELECT DISTINCT` com ordenação completa.
- Usar subquery `__in` que o banco otimiza como `EXISTS` ou semi-join:

```python
# Ruim
Debt.objects.filter(group__members__user=user).distinct()

# Certo
grupos_ids = GroupMember.objects.filter(user=user).values('group_id')
Debt.objects.filter(group_id__in=grupos_ids)
```

### 6.3 Count em queryset filtrado
- Quando o queryset já tem um `filter()` numa relação e você anota `Count()` da mesma relação, sempre usar `distinct=True` — sem ele, o COUNT pode contar apenas as linhas do JOIN que satisfazem o filtro, não o total real.

```python
Group.objects
    .filter(members__user=user)
    .annotate(member_count=Count('members', distinct=True))  # ← obrigatório
```

### 6.4 Prefetch com ordenação
- Quando um serializer precisa do item mais recente de uma relação, usar `Prefetch` com `order_by` no queryset interno — nunca `sorted()` em Python sobre o resultado prefetchado.

```python
# Ruim — ordena em Python depois de buscar tudo
sorted(obj.comprovantes.all(), key=lambda c: c.uploaded_at, reverse=True)

# Certo — banco entrega ordenado
Prefetch(
    'comprovantes',
    queryset=Comprovante.objects.order_by('-uploaded_at'),
)
```

### 6.5 Cache de resultado por request
- Quando o mesmo queryset de verificação é chamado em múltiplos métodos da view (ex: `get_queryset`, `get_serializer_context`, `perform_create`), cachear na instância da view:

```python
def _grupo_cached(self):
    if not hasattr(self, '_grupo'):
        self._grupo = _get_grupo(self.kwargs['grupo_pk'], self.request.user)
    return self._grupo
```

### 6.6 Filtro de membership em uma única JOIN
- Para verificar que **o mesmo usuário** satisfaz duas condições numa relação (ex: é membro E é admin), usar um único `.filter()` com múltiplos argumentos — não dois `.filter()` encadeados:

```python
# Ruim — 2 JOINs: "é membro E existe algum admin"
Group.objects.filter(members__user=user).filter(members__role='admin')

# Certo — 1 JOIN: "existe membro que é este user E é admin"
Group.objects.filter(members__user=user, members__role='admin')
```

### 6.7 Conexão com banco
- Configurar `CONN_MAX_AGE` via env var para reutilizar conexões em produção (PostgreSQL).
- Em desenvolvimento com SQLite, manter `CONN_MAX_AGE=0`.

### 6.8 Índices e exists()
- `db_index=True` em campos de filtro frequente.
- Usar `exists()` para checar presença, nunca `count() > 0`.

### 6.9 Paginação obrigatória
- Todo endpoint de lista usa `PageNumberPagination` com `PAGE_SIZE` definido no settings.
- Nunca retornar queryset sem paginar.

---

## 7. Tratamento de Exceções

- Nunca usar `except Exception` — capturar sempre o tipo específico esperado.
- Para ausência de OneToOne reverso, usar `django.core.exceptions.ObjectDoesNotExist` (evita import circular) ou o tipo exato `Model.DoesNotExist`.
- Nunca suprimir exceções com `pass` sem capturar um tipo específico — erros de programação ficam silenciosos.

```python
# Ruim
try:
    return str(obj.charge_link.token)
except Exception:
    return None

# Certo
try:
    return str(obj.charge_link.token)
except ObjectDoesNotExist:
    return None
```

---

## 8. Organização de Código

### 8.1 Imports
- Todos os imports ficam no topo do arquivo — nunca dentro de funções ou métodos.
- Importar dentro de método contorna o cache de módulos do Python, cria dependências invisíveis ao linter e dificulta rastreamento de dependências circulares.

### 8.2 Código morto
- Variáveis atribuídas e nunca usadas devem ser removidas imediatamente — não comentadas, não mantidas como "marcadores".

### 8.3 Estrutura de app
```
app/
  models.py
  serializers.py   ← List / Detail / Form por model
  services.py      ← regras de negócio
  views.py         ← orquestração fina (valida, chama service, responde)
  urls.py
```

---

## 9. Views

- Views só orquestram: recebem dados, chamam serviço, devolvem resposta.
- Usar `generics.*` e mixins explícitos quando possível — evitar duplicar lógica de queryset.
- Helpers de verificação de acesso (ex: `_get_grupo`) devem validar a condição em uma única query combinada.

### 9.1 Proteção de invariantes de negócio
- Regras de integridade que a UI poderia burlar (ex: remover o último admin do grupo) devem ser validadas na camada de serviço ou view, com erro explícito.

---

## 10. Migrations

- Toda migration gerada com `python manage.py makemigrations <app>` — nunca `makemigrations` geral em produção.
- Nunca editar migration já aplicada em produção.
- Migrations de dados usam `RunPython` com função de rollback definida.
- Revisar o SQL gerado com `sqlmigrate` antes de aplicar em produção.

---

## 11. Testes

- Cada app tem `tests/` com arquivos separados: `test_models.py`, `test_serializers.py`, `test_views.py`.
- Usar `APITestCase` do DRF para testar endpoints.
- Banco de testes usa `setUp` com `baker` / `factory_boy` — nunca fixtures JSON manuais.
- Coverage mínimo de 80% nos apps de negócio (`debts`, `groups`, `payments`).
