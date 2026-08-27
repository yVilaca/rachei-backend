"""
Mundo determinístico para os testes E2E full-stack.

reset_and_seed() zera os dados de domínio e recria um cenário fixo suficiente
para os fluxos P0. É chamado pelo comando `seed_e2e` e pelo endpoint de reset
(POST /api/__e2e__/reset/), este último só ativo sob settings_e2e (E2E_MODE).
"""
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.debts.models import Installment
from apps.debts.services import criar_despesa
from apps.groups.models import Group, GroupMember
from apps.payments.services import gerar_link_cobranca

# Senha forte (passa nos validators) usada por todas as contas de E2E.
PASSWORD = 'Zx9kLmnQ7er'


def _mk_user(email, name, phone):
    User = get_user_model()
    parts = name.split(' ', 1)
    u = User(
        username=email, email=email,
        first_name=parts[0], last_name=parts[1] if len(parts) > 1 else '',
        phone=phone, phone_verified=True, plan='free',
    )
    u.set_password(PASSWORD)
    u.save()
    return u


@transaction.atomic
def reset_and_seed():
    User = get_user_model()
    # Deletar os usuários cascateia grupos, dívidas, parcelas e acertos.
    User.objects.all().delete()

    alice = _mk_user('alice@e2e.test', 'Alice Costa', '+5599900000001')
    bob = _mk_user('bob@e2e.test', 'Bob Dias', '+5599900000002')

    grupo = Group.objects.create(name='Casa', emoji='🏠', created_by=alice)
    GroupMember.objects.create(group=grupo, user=alice, role=GroupMember.ROLE_ADMIN, status=GroupMember.STATUS_ATIVO)
    GroupMember.objects.create(group=grupo, user=bob, role=GroupMember.ROLE_MEMBER, status=GroupMember.STATUS_ATIVO)

    # Fluxo 3 (confirmação dupla): bob deve 5000 à alice ("Mercado").
    mercado = criar_despesa(
        grupo=grupo, paid_by=alice, created_by=alice, description='Mercado',
        total_amount_cents=10000, split_type='custom',
        parcelas_data=[{'debtor': alice, 'amount_cents': 5000}, {'debtor': bob, 'amount_cents': 5000}],
    )
    # Fluxo 4 (compensação): alice deve 4000 ao bob ("Uber") → dívida mútua.
    uber = criar_despesa(
        grupo=grupo, paid_by=bob, created_by=bob, description='Uber',
        total_amount_cents=4000, split_type='custom',
        parcelas_data=[{'debtor': alice, 'amount_cents': 4000}],
    )

    # Link de cobrança da parcela do bob no Mercado (para o E2E da página pública).
    parcela_bob = Installment.objects.get(debt=mercado, debtor=bob)
    link = gerar_link_cobranca(parcela=parcela_bob, solicitado_por=alice)

    return {
        'password': PASSWORD,
        'alice': {'id': alice.pk, 'email': alice.email, 'name': alice.get_full_name()},
        'bob': {'id': bob.pk, 'email': bob.email, 'name': bob.get_full_name()},
        'group': {'id': str(grupo.id), 'name': grupo.name},
        'debt_mercado': {'id': str(mercado.id)},
        'debt_uber': {'id': str(uber.id)},
        'charge_token': str(link.token),
    }
