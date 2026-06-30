# Models — Exemplos

## UUID vs BigAutoField

```python
# Modelo de negócio — UUID
class Debt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column='dsp_id')
    class Meta:
        db_table = 'despesas'

# Tabela de junção — BigAutoField
class GroupMember(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='mgp_id')
    class Meta:
        db_table = 'membros_grupo'
```

## db_column em todos os campos

```python
class Installment(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column='pcl_id')
    debt         = models.ForeignKey(Debt, db_column='pcl_despesa_id', ...)
    debtor       = models.ForeignKey(User, db_column='pcl_devedor_id', ...)
    amount_cents = models.PositiveIntegerField(db_column='pcl_valor_centavos')
    status       = models.CharField(db_column='pcl_status', db_index=True, ...)
    paid_at      = models.DateTimeField(null=True, db_column='pcl_pago_em')

    class Meta:
        db_table = 'parcelas'
```

## Índice parcial

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
