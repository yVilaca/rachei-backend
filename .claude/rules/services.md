# Services — Exemplos e Padrões

## Exceções stdlib → conversão na view

```python
# service.py — exceções stdlib apenas
@transaction.atomic
def criar_despesa(*, grupo, paid_by, description, total_amount_cents, split_type, parcelas_data):
    if paid_by.pk not in member_ids:
        raise PermissionError('Você não é membro deste grupo.')
    if debtor_ids - member_ids:
        raise ValueError('Um ou mais devedores não são membros do grupo.')

# views.py — conversão para DRF
try:
    despesa = criar_despesa(...)
except PermissionError as e:
    raise PermissionDenied(str(e))
except ValueError as e:
    raise ValidationError(str(e))
```

## Update atômico de status (nunca .save())

```python
# Ruim — sobrescreve campos modificados concorrentemente
parcela.status = 'paid'
parcela.save()

# Certo — atualiza apenas os campos necessários, atomic
Installment.objects.filter(pk=parcela.pk).update(
    status='paid',
    paid_at=timezone.now(),
)
parcela.refresh_from_db(fields=['status', 'paid_at'])
```

## Bulk create

```python
# Inserção em lote — 1 INSERT para N parcelas
Installment.objects.bulk_create([
    Installment(debt=despesa, debtor=p['debtor'], amount_cents=p['amount_cents'])
    for p in parcelas_data
])

# Idempotente — duplicate silenciado
NotificacaoLida.objects.bulk_create(
    [NotificacaoLida(usuario=user, evento_id=eid) for eid in validos],
    ignore_conflicts=True,
)
```

## Divisão justa de centavos

```python
n = len(parcelas_data)
base = total_amount_cents // n
remainder = total_amount_cents % n
for i, p in enumerate(parcelas_data):
    p['amount_cents'] = base + (1 if i < remainder else 0)
# soma sempre == total_amount_cents
```

## Exceção específica (nunca except Exception)

```python
# Ruim
try:
    return str(obj.charge_link.token)
except Exception:
    return None

# Certo
from django.core.exceptions import ObjectDoesNotExist

try:
    return str(obj.charge_link.token)
except ObjectDoesNotExist:
    return None
```
