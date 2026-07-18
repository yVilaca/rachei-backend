"""
Edição e exclusão de dívida.
Regras: só o credor edita/exclui; valores e exclusão só enquanto ninguém pagou
(a descrição é sempre editável). Outsider recebe 404; membro não-credor, 403.
"""
from .helpers import SecurityTestCase

DEBT = '/api/despesas/{}/'


class DebtEditTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)  # credor

    def test_creditor_edits_description(self):
        r = self.vic.patch(DEBT.format(self.s.debt_id), {'description': 'Novo nome'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['description'], 'Novo nome')
        self.assertTrue(r.data['editavel'])

    def test_creditor_edits_values_when_editable(self):
        r = self.vic.patch(DEBT.format(self.s.debt_id), {
            'description': 'Jantar', 'total_amount_cents': 8000, 'split_type': 'custom',
            'parcelas': [
                {'debtor_id': int(self.s.byt_id), 'amount_cents': 3000},
                {'debtor_id': int(self.s.mb3_id), 'amount_cents': 5000},
            ],
        }, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['total_amount_cents'], 8000)
        self.assertEqual(sorted(p['amount_cents'] for p in r.data['parcelas']), [3000, 5000])

    def test_non_creditor_member_cannot_edit(self):
        r = self.api(self.s.byt_t).patch(DEBT.format(self.s.debt_id), {'description': 'x'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_outsider_gets_404(self):
        r = self.api(self.s.atk_t).patch(DEBT.format(self.s.debt_id), {'description': 'x'}, format='json')
        self.assertEqual(r.status_code, 404)


class DebtDeleteTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)

    def test_creditor_deletes_when_editable(self):
        self.assertEqual(self.vic.delete(DEBT.format(self.s.debt_id)).status_code, 204)
        self.assertEqual(self.vic.get(DEBT.format(self.s.debt_id)).status_code, 404)

    def test_non_creditor_member_cannot_delete(self):
        self.assertEqual(self.api(self.s.byt_t).delete(DEBT.format(self.s.debt_id)).status_code, 403)

    def test_outsider_gets_404(self):
        self.assertEqual(self.api(self.s.atk_t).delete(DEBT.format(self.s.debt_id)).status_code, 404)


class DebtLockedAfterPaymentTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)
        # devedor declara pagamento → dívida deixa de ser alterável
        self.api(self.s.byt_t).post(f'/api/parcelas/{self.s.parcela_byt}/comprovante/', {}, format='json')

    def test_debt_marked_not_editable(self):
        detail = self.vic.get(DEBT.format(self.s.debt_id)).data
        self.assertFalse(detail['editavel'])

    def test_value_edit_blocked(self):
        r = self.vic.patch(DEBT.format(self.s.debt_id), {
            'description': 'x', 'total_amount_cents': 8000, 'split_type': 'custom',
            'parcelas': [{'debtor_id': int(self.s.byt_id), 'amount_cents': 8000}],
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_description_edit_still_allowed(self):
        r = self.vic.patch(DEBT.format(self.s.debt_id), {'description': 'Só descrição'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['description'], 'Só descrição')

    def test_delete_blocked(self):
        self.assertEqual(self.vic.delete(DEBT.format(self.s.debt_id)).status_code, 400)
