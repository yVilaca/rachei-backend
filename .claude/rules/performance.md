# Performance de Querysets — Exemplos

## Subquery em vez de DISTINCT

```python
# Ruim — SELECT DISTINCT força ordenação completa
Debt.objects.filter(group__members__user=user).distinct()

# Certo — subquery avaliada pelo banco como semi-join
grupos_ids = GroupMember.objects.filter(user=user).values('group_id')
Debt.objects.filter(group_id__in=grupos_ids)
```

## Count com distinct

```python
# Sem distinct=True, o COUNT pode contar só as linhas do JOIN do filter
Group.objects
    .filter(members__user=user)
    .annotate(member_count=Count('members', distinct=True))  # obrigatório
```

## Prefetch com order_by

```python
# Ruim — sorted() em Python sobre lista prefetchada
sorted(obj.comprovantes.all(), key=lambda c: c.uploaded_at, reverse=True)

# Certo — banco entrega já ordenado
Prefetch(
    'comprovantes',
    queryset=Comprovante.objects.order_by('-uploaded_at'),
)
```

## Filtro de membership em JOIN único

```python
# Ruim — dois .filter() = dois JOINs separados
# Semântica errada: "é membro E existe algum admin no grupo"
Group.objects.filter(members__user=user).filter(members__role='admin')

# Certo — único .filter() = um JOIN com duas condições
# Semântica correta: "existe membro que é este user E é admin"
Group.objects.filter(members__user=user, members__role='admin')
```

## Cache de lookup por request

```python
# Evita chamar o banco 2-3x por request para a mesma verificação
def _grupo_cached(self):
    if not hasattr(self, '_grupo'):
        self._grupo = _get_grupo(self.kwargs['grupo_pk'], self.request.user)
    return self._grupo
```

## Double query em get_object

```python
# Ruim — verifica membership E refaz query com prefetch
def get_object(self):
    grupo = _get_grupo(self.kwargs['pk'], self.request.user)   # query 1
    grupo = Group.objects.prefetch_related(...).get(pk=grupo.pk)  # query 2

# Certo — uma query só com membership + prefetch
def get_object(self):
    grupo = (
        Group.objects
        .filter(pk=self.kwargs['pk'], members__user=self.request.user)
        .select_related('created_by')
        .prefetch_related(Prefetch('members', queryset=GroupMember.objects.select_related('user')))
        .first()
    )
    if not grupo:
        raise NotFound('Grupo não encontrado.')
    return grupo
```
