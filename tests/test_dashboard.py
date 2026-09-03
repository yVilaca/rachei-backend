"""
Dashboard: corretude aritmética dos totais e do saldo por pessoa (agora
agregados no banco). Cenário build_scenario: victim credora de byt (5000) e
mb3 (5000); no setUp byt vira credor da victim em 4000 (Uber).
"""
from .helpers import SecurityTestCase

DASHBOARD = '/api/dashboard/'


class DashboardTotalsTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)
        self.byt = self.api(self.s.byt_t)
        # byt credor, victim deve 4000
        self.byt.post('/api/despesas/', {
            'grupo_id': self.s.group_id, 'description': 'Uber', 'total_amount_cents': 4000,
            'split_type': 'custom',
            'parcelas': [{'debtor_id': int(self.s.vic_id), 'amount_cents': 4000}],
        }, format='json')

    def _saldo(self, data, uid):
        return next((p['balance_cents'] for p in data['saldo_por_pessoa']
                     if p['user']['id'] == uid), None)

    def test_totais_da_credora(self):
        r = self.vic.get(DASHBOARD)
        self.assertEqual(r.status_code, 200, r.content)
        # recebe de byt (5000) + mb3 (5000); deve 4000 a byt
        self.assertEqual(r.data['total_a_receber'], 10000)
        self.assertEqual(r.data['total_a_pagar'], 4000)
        # saldo líquido: byt = +5000 - 4000 = +1000; mb3 = +5000
        self.assertEqual(self._saldo(r.data, int(self.s.byt_id)), 1000)
        self.assertEqual(self._saldo(r.data, int(self.s.mb3_id)), 5000)

    def test_totais_do_devedor(self):
        r = self.byt.get(DASHBOARD)
        self.assertEqual(r.status_code, 200, r.content)
        # byt: recebe 4000 (Uber) da victim; deve 5000 (Jantar) à victim
        self.assertEqual(r.data['total_a_receber'], 4000)
        self.assertEqual(r.data['total_a_pagar'], 5000)
        # saldo com a victim: +4000 - 5000 = -1000
        self.assertEqual(self._saldo(r.data, int(self.s.vic_id)), -1000)

    def test_totais_vazios_sao_zero(self):
        # mb3 só deve; não recebe nada
        r = self.api(self.s.mb3_t).get(DASHBOARD)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['total_a_receber'], 0)
        self.assertEqual(r.data['total_a_pagar'], 5000)
