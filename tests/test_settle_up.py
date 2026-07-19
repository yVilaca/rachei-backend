"""
Acertar contas (compensação / netting entre duas pessoas).

Uma parte propõe; a outra confirma. Ao confirmar, as dívidas pendentes nos dois
sentidos são quitadas por compensação e sobra apenas a dívida líquida.

Cenário: vítima é credora de byt em 5000 (Jantar) e mb3 em 5000. No setUp,
byt vira credor da vítima em 4000 (Uber). Logo entre vítima↔byt há dívida mútua
(5000 vs 4000 → líquido 1000 de byt para a vítima). Já vítima↔mb3 é unilateral.
"""
from apps.debts.models import Debt, Installment
from apps.payments.models import Acerto
from apps.users.models import AuditLog
from .helpers import SecurityTestCase

ACERTAR = '/api/acertar/'


def _confirmar(pk):
    return f'/api/acertar/{pk}/confirmar/'


def _rejeitar(pk):
    return f'/api/acertar/{pk}/rejeitar/'


class SettleUpTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()  # victim credora; byt/mb3 devedores
        vic = self.api(self.s.vic_t)
        byt = self.api(self.s.byt_t)
        # Dívida em que byt é credor e a vítima deve 4000 → cria mutualidade vic↔byt
        u = byt.post('/api/despesas/', {
            'grupo_id': self.s.group_id, 'description': 'Uber', 'total_amount_cents': 4000,
            'split_type': 'custom',
            'parcelas': [{'debtor_id': int(self.s.vic_id), 'amount_cents': 4000}],
        }, format='json')
        assert u.status_code == 201, u.content
        self.uber_parcela = u.data['parcelas'][0]['id']
        self.vic, self.byt = vic, byt

    # ── resumo ────────────────────────────────────────────────────────────────
    def test_resumo_saldo_liquido_e_compensavel(self):
        r = self.vic.get(ACERTAR)
        self.assertEqual(r.status_code, 200, r.content)
        por_pessoa = {p['pessoa']['id']: p for p in r.data['pessoas']}
        # vs byt: recebo 5000, devo 4000 → saldo +1000, compensável
        self.assertEqual(por_pessoa[int(self.s.byt_id)]['saldo_cents'], 1000)
        self.assertTrue(por_pessoa[int(self.s.byt_id)]['compensavel'])
        # vs mb3: unilateral (recebo 5000, devo 0) → não compensável
        self.assertEqual(por_pessoa[int(self.s.mb3_id)]['saldo_cents'], 5000)
        self.assertFalse(por_pessoa[int(self.s.mb3_id)]['compensavel'])

    # ── propor ──────────────────────────────────────────────────────────────
    def test_propor_cria_acerto_pendente_sem_alterar_parcelas(self):
        r = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIn('id', r.data)
        acerto = Acerto.objects.get(pk=r.data['id'])
        self.assertEqual(acerto.status, Acerto.STATUS_PENDING)
        # nada quitado ainda
        self.assertEqual(
            Installment.objects.get(pk=self.s.parcela_byt).status, Installment.STATUS_PENDING
        )
        self.assertEqual(
            Installment.objects.get(pk=self.uber_parcela).status, Installment.STATUS_PENDING
        )

    def test_propor_sem_mutualidade_falha(self):
        # vs mb3 não há dívida mútua → 400
        r = self.vic.post(ACERTAR, {'para_id': int(self.s.mb3_id)}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_propor_reutiliza_pendente(self):
        a = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        b = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        self.assertEqual(a.data['id'], b.data['id'])
        self.assertEqual(Acerto.objects.filter(de=self.s.vic_id, status='pending').count(), 1)

    def test_propor_para_id_obrigatorio(self):
        r = self.vic.post(ACERTAR, {}, format='json')
        self.assertEqual(r.status_code, 400)

    # ── confirmar (compensação) ──────────────────────────────────────────────
    def test_confirmar_compensa_e_cria_divida_liquida(self):
        prop = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        acerto_id = prop.data['id']
        r = self.byt.post(_confirmar(acerto_id), format='json')
        self.assertEqual(r.status_code, 200, r.content)

        # ambos os sentidos foram quitados
        self.assertEqual(
            Installment.objects.get(pk=self.s.parcela_byt).status, Installment.STATUS_PAID
        )
        self.assertEqual(
            Installment.objects.get(pk=self.uber_parcela).status, Installment.STATUS_PAID
        )
        # sobra UMA dívida líquida de 1000, byt devedor → vítima credora
        liquida = Debt.objects.filter(description='Acerto de contas')
        self.assertEqual(liquida.count(), 1)
        d = liquida.first()
        self.assertEqual(d.total_amount_cents, 1000)
        self.assertEqual(d.paid_by_id, int(self.s.vic_id))
        parc = d.installments.get()
        self.assertEqual(parc.debtor_id, int(self.s.byt_id))
        self.assertEqual(parc.amount_cents, 1000)
        self.assertEqual(parc.status, Installment.STATUS_PENDING)
        # mb3 (unilateral) intocado
        self.assertEqual(
            Installment.objects.get(pk=self.s.parcela_mb3).status, Installment.STATUS_PENDING
        )
        self.assertEqual(Acerto.objects.get(pk=acerto_id).status, Acerto.STATUS_CONFIRMED)

    def test_apenas_destinatario_confirma(self):
        prop = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        # mb3 (nada a ver) tenta confirmar → 404 (não vaza existência)
        r = self.api(self.s.mb3_t).post(_confirmar(prop.data['id']), format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Acerto.objects.get(pk=prop.data['id']).status, Acerto.STATUS_PENDING)

    def test_proponente_nao_confirma_o_proprio(self):
        prop = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        r = self.vic.post(_confirmar(prop.data['id']), format='json')
        self.assertEqual(r.status_code, 404)  # vic é `de`, não `para`

    def test_confirmar_duas_vezes_falha(self):
        prop = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        self.byt.post(_confirmar(prop.data['id']), format='json')
        r = self.byt.post(_confirmar(prop.data['id']), format='json')
        self.assertEqual(r.status_code, 400)  # já resolvido

    # ── rejeitar ────────────────────────────────────────────────────────────
    def test_rejeitar_nao_altera_parcelas(self):
        prop = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        r = self.byt.post(_rejeitar(prop.data['id']), format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Acerto.objects.get(pk=prop.data['id']).status, Acerto.STATUS_REJECTED)
        self.assertEqual(
            Installment.objects.get(pk=self.s.parcela_byt).status, Installment.STATUS_PENDING
        )
        self.assertFalse(Debt.objects.filter(description='Acerto de contas').exists())

    def test_apenas_destinatario_rejeita(self):
        prop = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        r = self.api(self.s.mb3_t).post(_rejeitar(prop.data['id']), format='json')
        self.assertEqual(r.status_code, 404)

    # ── auditoria / auth ──────────────────────────────────────────────────────
    def test_acerto_e_auditado(self):
        prop = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        self.assertTrue(AuditLog.objects.filter(event=AuditLog.SETTLE_DECLARED).exists())
        self.byt.post(_confirmar(prop.data['id']), format='json')
        self.assertTrue(AuditLog.objects.filter(event=AuditLog.SETTLE_CONFIRMED).exists())

    def test_requires_auth(self):
        self.assertEqual(self.api().get(ACERTAR).status_code, 401)
        self.assertEqual(self.api().post(ACERTAR, {}, format='json').status_code, 401)
