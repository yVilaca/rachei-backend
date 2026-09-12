"""
Atribuir dívida a um CONTATO PENDENTE (convidado por telefone, ainda sem conta).

Propriedade de segurança central: a dívida só se vincula a uma pessoa real na
verificação do telefone (OTP) — quem prova ser dono do número herda a parcela.
Até lá, é uma parcela sem usuário (debtor nulo, debtor_contato preenchido).
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.debts.models import Installment
from apps.groups.models import ContatoPendente, GroupMember
from apps.users.views import _link_pending_contacts
from .helpers import SecurityTestCase, STRONG_PWD

User = get_user_model()
DESPESAS = '/api/despesas/'
PENDING_PHONE = '+5599900008888'


class PendingDebtorTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)
        r = self.vic.post(
            f'/api/grupos/{self.s.group_id}/membros/',
            {'phone': PENDING_PHONE, 'name': 'Fulano Pendente'}, format='json',
        )
        assert r.status_code == 201, r.content
        self.contato = ContatoPendente.objects.get(phone=PENDING_PHONE)

    def _criar_para_contato(self, amount=5000):
        return self.vic.post(DESPESAS, {
            'grupo_id': self.s.group_id, 'description': 'Bar', 'total_amount_cents': amount,
            'split_type': 'custom',
            'parcelas': [{'debtor_contato_id': self.contato.pk, 'amount_cents': amount}],
        }, format='json')

    def test_cria_divida_para_contato_pendente(self):
        r = self._criar_para_contato(5000)
        self.assertEqual(r.status_code, 201, r.content)
        parcela = r.data['parcelas'][0]
        self.assertTrue(parcela['debtor']['pending'])
        self.assertEqual(parcela['debtor']['name'], 'Fulano Pendente')
        inst = Installment.objects.get(pk=parcela['id'])
        self.assertIsNone(inst.debtor_id)
        self.assertEqual(inst.debtor_contato_id, self.contato.pk)
        self.assertEqual(inst.status, Installment.STATUS_PENDING)

    def test_telefone_do_contato_nao_vaza(self):
        r = self._criar_para_contato(5000)
        self.assertNotIn(PENDING_PHONE, str(r.data))

    def test_contato_fora_do_grupo_recusado(self):
        outro = ContatoPendente.objects.create(phone='+5599900007777', name='Alheio', criado_por=None)
        r = self.vic.post(DESPESAS, {
            'grupo_id': self.s.group_id, 'description': 'X', 'total_amount_cents': 1000, 'split_type': 'custom',
            'parcelas': [{'debtor_contato_id': outro.pk, 'amount_cents': 1000}],
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_parcela_sem_devedor_recusada(self):
        r = self.vic.post(DESPESAS, {
            'grupo_id': self.s.group_id, 'description': 'X', 'total_amount_cents': 1000, 'split_type': 'custom',
            'parcelas': [{'amount_cents': 1000}],
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_vinculo_so_no_cadastro_por_otp(self):
        inst_id = self._criar_para_contato(5000).data['parcelas'][0]['id']

        # A pessoa se cadastra com aquele telefone; _link_pending_contacts roda na
        # verificação por OTP e vincula a parcela ao usuário real.
        c = APIClient()
        reg = c.post('/api/auth/register/', {
            'name': 'Fulano Pendente', 'email': 'fulano@example.invalid',
            'phone': PENDING_PHONE, 'password': STRONG_PWD,
        }, format='json')
        self.assertEqual(reg.status_code, 201, reg.content)
        novo = User.objects.get(email='fulano@example.invalid')
        _link_pending_contacts(novo)

        inst = Installment.objects.get(pk=inst_id)
        self.assertEqual(inst.debtor_id, novo.pk)          # migrou para o usuário real
        self.assertIsNone(inst.debtor_contato_id)
        self.assertFalse(ContatoPendente.objects.filter(pk=self.contato.pk).exists())
        m = GroupMember.objects.get(group_id=self.s.group_id, user=novo)
        self.assertEqual(m.status, GroupMember.STATUS_PENDENTE_CONFIRMACAO)
