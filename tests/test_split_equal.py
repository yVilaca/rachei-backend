"""
Divisão igualitária (split "equal") — aritmética de centavos e conservação.

Num app de dinheiro, o ponto onde bugs se escondem é a distribuição do resto:
`base = total // n`, `remainder = total % n`, e os primeiros `remainder`
devedores recebem +1 centavo. A invariante sagrada é **soma == total** (nunca
some nem cria dinheiro). Também cobre a validação de entrada do endpoint.
"""
from .helpers import SecurityTestCase

DESPESAS = '/api/despesas/'


class EqualSplitMoneyTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()  # victim credor; byt/mb3 devedores membros
        self.vic = self.api(self.s.vic_t)

    def _criar_equal(self, total, debtor_ids):
        """Cria despesa equal; amount_cents enviado é placeholder (o serviço recalcula)."""
        return self.vic.post(DESPESAS, {
            'grupo_id': self.s.group_id,
            'description': 'Racha',
            'total_amount_cents': total,
            'split_type': 'equal',
            'parcelas': [{'debtor_id': int(d), 'amount_cents': 1} for d in debtor_ids],
        }, format='json')

    def _por_devedor(self, resp):
        return {str(p['debtor']['id']): p['amount_cents'] for p in resp.data['parcelas']}

    def test_divisivel_reparte_igualmente(self):
        r = self._criar_equal(9000, [self.s.byt_id, self.s.mb3_id])
        self.assertEqual(r.status_code, 201, r.content)
        por = self._por_devedor(r)
        self.assertEqual(por[str(self.s.byt_id)], 4500)
        self.assertEqual(por[str(self.s.mb3_id)], 4500)
        self.assertEqual(sum(por.values()), 9000)

    def test_resto_vai_para_os_primeiros_devedores(self):
        # 10001 / 2 -> base 5000, resto 1 -> o PRIMEIRO da lista recebe o centavo.
        r = self._criar_equal(10001, [self.s.byt_id, self.s.mb3_id])
        self.assertEqual(r.status_code, 201, r.content)
        por = self._por_devedor(r)
        self.assertEqual(por[str(self.s.byt_id)], 5001)  # primeiro
        self.assertEqual(por[str(self.s.mb3_id)], 5000)
        self.assertEqual(sum(por.values()), 10001)

    def test_resto_em_tres_vias(self):
        # 10000 / 3 -> 3334 + 3333 + 3333 (victim entra como 3º devedor).
        r = self._criar_equal(10000, [self.s.byt_id, self.s.mb3_id, self.s.vic_id])
        self.assertEqual(r.status_code, 201, r.content)
        por = self._por_devedor(r)
        self.assertEqual(por[str(self.s.byt_id)], 3334)
        self.assertEqual(por[str(self.s.mb3_id)], 3333)
        self.assertEqual(por[str(self.s.vic_id)], 3333)
        self.assertEqual(sum(por.values()), 10000)

    def test_conservacao_soma_igual_ao_total(self):
        # Invariante: para qualquer total >= n, a soma das parcelas == total e a
        # diferença entre a maior e a menor parcela nunca passa de 1 centavo.
        for total in (2, 3, 100, 101, 999, 1000, 1001, 9999, 10000, 10001, 123457):
            r = self._criar_equal(total, [self.s.byt_id, self.s.mb3_id])
            self.assertEqual(r.status_code, 201, r.content)
            valores = [p['amount_cents'] for p in r.data['parcelas']]
            self.assertEqual(sum(valores), total, f'total={total} não conserva')
            self.assertLessEqual(max(valores) - min(valores), 1, f'total={total} desbalanceado')

    def test_equal_ignora_valores_enviados(self):
        # Cliente manda valores tortos; no equal o servidor recalcula do total.
        r = self.vic.post(DESPESAS, {
            'grupo_id': self.s.group_id, 'description': 'Racha', 'total_amount_cents': 8000,
            'split_type': 'equal',
            'parcelas': [
                {'debtor_id': int(self.s.byt_id), 'amount_cents': 7999},
                {'debtor_id': int(self.s.mb3_id), 'amount_cents': 1},
            ],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        por = self._por_devedor(r)
        self.assertEqual(por[str(self.s.byt_id)], 4000)
        self.assertEqual(por[str(self.s.mb3_id)], 4000)


class DespesaValidationTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)

    def _post(self, body):
        base = {'grupo_id': self.s.group_id, 'description': 'X', 'split_type': 'custom'}
        return self.vic.post(DESPESAS, {**base, **body}, format='json')

    def test_custom_soma_diferente_do_total_falha(self):
        r = self._post({
            'total_amount_cents': 10000,
            'parcelas': [
                {'debtor_id': int(self.s.byt_id), 'amount_cents': 5000},
                {'debtor_id': int(self.s.mb3_id), 'amount_cents': 4000},  # soma 9000 != 10000
            ],
        })
        self.assertEqual(r.status_code, 400)

    def test_valor_de_parcela_zero_falha(self):
        r = self._post({
            'total_amount_cents': 5000,
            'parcelas': [{'debtor_id': int(self.s.byt_id), 'amount_cents': 0}],
        })
        self.assertEqual(r.status_code, 400)

    def test_total_zero_falha(self):
        r = self._post({
            'total_amount_cents': 0,
            'parcelas': [{'debtor_id': int(self.s.byt_id), 'amount_cents': 0}],
        })
        self.assertEqual(r.status_code, 400)

    def test_sem_parcelas_falha(self):
        r = self._post({'total_amount_cents': 5000, 'parcelas': []})
        self.assertEqual(r.status_code, 400)

    def test_devedor_fora_do_grupo_falha(self):
        # outsider não é membro do grupo da vítima → rejeitado.
        _, out_id = self.register('outsider')
        r = self._post({
            'total_amount_cents': 5000,
            'parcelas': [{'debtor_id': int(out_id), 'amount_cents': 5000}],
        })
        self.assertEqual(r.status_code, 400)
