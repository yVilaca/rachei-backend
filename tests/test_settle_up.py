"""
Acertar contas (settle up par a par, em lote).
Devedor declara; credor confirma (confirmação dupla). Só mexe nas próprias
parcelas; auditado. Cobre: com uma pessoa, com todos, e a confirmação.
"""
from apps.debts.models import Installment
from apps.users.models import AuditLog
from .helpers import SecurityTestCase

ACERTAR = '/api/acertar/'
CONFIRMAR = '/api/acertar/confirmar/'


class SettleUpTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()  # victim credor; bystander/member3 devedores
        # member3 também deve à vítima; criamos uma 2ª dívida onde bystander é credor
        # e a vítima deve, para testar "acertar com todos".
        vic = self.api(self.s.vic_t)
        byt = self.api(self.s.byt_t)
        # dívida em que bystander é credor e victim deve
        byt.post('/api/despesas/', {
            'grupo_id': self.s.group_id, 'description': 'Uber', 'total_amount_cents': 4000,
            'split_type': 'custom',
            'parcelas': [{'debtor_id': int(self.s.vic_id), 'amount_cents': 4000}],
        }, format='json')
        self.vic, self.byt = vic, byt

    def test_resumo_lists_debts(self):
        # bystander deve 5000 à vítima (do cenário base)
        r = self.byt.get(ACERTAR)
        self.assertEqual(r.status_code, 200)
        deve = {p['pessoa']['id']: p['valor_cents'] for p in r.data['voce_deve']}
        self.assertEqual(deve.get(int(self.s.vic_id)), 5000)

    def test_settle_with_one_person_declares(self):
        r = self.byt.post(ACERTAR, {'para_id': int(self.s.vic_id)}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['declaradas'], 1)
        # a parcela do bystander p/ vítima ficou awaiting
        inst = Installment.objects.get(pk=self.s.parcela_byt)
        self.assertEqual(inst.status, Installment.STATUS_AWAITING)

    def test_settle_all_declares_across_creditors(self):
        # a vítima deve ao bystander (Uber). "Acertar tudo" sem para_id.
        r = self.vic.post(ACERTAR, {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreaterEqual(r.data['declaradas'], 1)

    def test_only_own_installments_touched(self):
        # bystander declara acerto; a parcela do member3 (outro devedor) não muda
        self.byt.post(ACERTAR, {'para_id': int(self.s.vic_id)}, format='json')
        mb3 = Installment.objects.get(pk=self.s.parcela_mb3)
        self.assertEqual(mb3.status, Installment.STATUS_PENDING)

    def test_creditor_confirms_settlement(self):
        self.byt.post(ACERTAR, {'para_id': int(self.s.vic_id)}, format='json')
        r = self.vic.post(CONFIRMAR, {'de_id': int(self.s.byt_id)}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['confirmadas'], 1)
        inst = Installment.objects.get(pk=self.s.parcela_byt)
        self.assertEqual(inst.status, Installment.STATUS_PAID)

    def test_non_creditor_cannot_confirm_others(self):
        # bystander declara; member3 (não é credor daquilo) tenta confirmar → nada
        self.byt.post(ACERTAR, {'para_id': int(self.s.vic_id)}, format='json')
        r = self.api(self.s.mb3_t).post(CONFIRMAR, {'de_id': int(self.s.byt_id)}, format='json')
        self.assertEqual(r.status_code, 400)  # nenhum acerto p/ confirmar
        inst = Installment.objects.get(pk=self.s.parcela_byt)
        self.assertEqual(inst.status, Installment.STATUS_AWAITING)  # intacto

    def test_settle_is_audited(self):
        self.byt.post(ACERTAR, {'para_id': int(self.s.vic_id)}, format='json')
        self.assertTrue(AuditLog.objects.filter(event=AuditLog.SETTLE_DECLARED).exists())
        self.vic.post(CONFIRMAR, {'de_id': int(self.s.byt_id)}, format='json')
        self.assertTrue(AuditLog.objects.filter(event=AuditLog.SETTLE_CONFIRMED).exists())

    def test_requires_auth(self):
        self.assertEqual(self.api().get(ACERTAR).status_code, 401)
        self.assertEqual(self.api().post(ACERTAR, {}, format='json').status_code, 401)
