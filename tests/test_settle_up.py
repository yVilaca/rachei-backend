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

    def test_propor_com_selecao_valida(self):
        r = self.vic.post(ACERTAR, {
            'para_id': int(self.s.byt_id),
            'parcela_ids': [str(self.s.parcela_byt), str(self.uber_parcela)],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Acerto.objects.get(pk=r.data['id']).parcelas.count(), 2)

    def test_propor_selecao_de_um_lado_so_falha(self):
        # só a dívida "Uber" (um sentido) → sem mutualidade na seleção → 400
        r = self.vic.post(ACERTAR, {
            'para_id': int(self.s.byt_id),
            'parcela_ids': [str(self.uber_parcela)],
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_propor_selecao_com_parcela_alheia_falha(self):
        # parcela do mb3 não é candidata do par vic↔byt
        r = self.vic.post(ACERTAR, {
            'para_id': int(self.s.byt_id),
            'parcela_ids': [str(self.s.parcela_byt), str(self.s.parcela_mb3)],
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_confirmar_quita_apenas_selecionadas(self):
        # Cria uma 2ª dívida onde byt deve à vic (Cinema 2000). Seleciona só
        # Jantar + Uber; Cinema deve permanecer pendente.
        d = self.vic.post('/api/despesas/', {
            'grupo_id': self.s.group_id, 'description': 'Cinema', 'total_amount_cents': 2000,
            'split_type': 'custom',
            'parcelas': [{'debtor_id': int(self.s.byt_id), 'amount_cents': 2000}],
        }, format='json')
        cinema_parcela = d.data['parcelas'][0]['id']

        prop = self.vic.post(ACERTAR, {
            'para_id': int(self.s.byt_id),
            'parcela_ids': [str(self.s.parcela_byt), str(self.uber_parcela)],
        }, format='json')
        r = self.byt.post(_confirmar(prop.data['id']), format='json')
        self.assertEqual(r.status_code, 200, r.content)

        # Uber (4000) totalmente abatida
        self.assertEqual(Installment.objects.get(pk=self.uber_parcela).status, Installment.STATUS_PAID)
        # Cinema NÃO foi selecionada → segue pendente
        self.assertEqual(Installment.objects.get(pk=cinema_parcela).status, Installment.STATUS_PENDING)
        # não cria dívida nova
        self.assertFalse(Debt.objects.filter(description='Acerto de contas').exists())
        # Jantar (5000) tinha só 4000 abatível → resíduo de 1000 segue pendente na própria parcela
        jantar = Installment.objects.get(pk=self.s.parcela_byt)
        self.assertEqual(jantar.status, Installment.STATUS_PENDING)
        self.assertEqual(jantar.amount_cents, 1000)

    # ── confirmar (compensação) ──────────────────────────────────────────────
    def test_confirmar_abate_selecionadas_sem_criar_divida(self):
        prop = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        acerto_id = prop.data['id']
        r = self.byt.post(_confirmar(acerto_id), format='json')
        self.assertEqual(r.status_code, 200, r.content)

        # Não cria dívida "Acerto de contas"
        self.assertFalse(Debt.objects.filter(description='Acerto de contas').exists())

        # Uber (4000) foi abatida por completo
        uber = Installment.objects.get(pk=self.uber_parcela)
        self.assertEqual(uber.status, Installment.STATUS_PAID)
        self.assertEqual(uber.paid_via, Installment.PAID_VIA_COMPENSATION)

        # Jantar (5000): 4000 abatidos, 1000 de resíduo segue pendente na parcela original
        jantar = Installment.objects.get(pk=self.s.parcela_byt)
        self.assertEqual(jantar.status, Installment.STATUS_PENDING)
        self.assertEqual(jantar.amount_cents, 1000)

        # o total da dívida Jantar continua íntegro (1000 pendente + 4000 pago + 5000 mb3)
        jantar_debt = jantar.debt
        self.assertEqual(
            sum(jantar_debt.installments.values_list('amount_cents', flat=True)), 10000
        )

        # mb3 (unilateral) intocado
        self.assertEqual(
            Installment.objects.get(pk=self.s.parcela_mb3).status, Installment.STATUS_PENDING
        )
        self.assertEqual(Acerto.objects.get(pk=acerto_id).status, Acerto.STATUS_CONFIRMED)

    def test_compensacao_tem_vinculo_de_auditoria(self):
        prop = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        self.byt.post(_confirmar(prop.data['id']), format='json')
        acerto = Acerto.objects.get(pk=prop.data['id'])
        # as parcelas quitadas por compensação estão ligadas ao acerto...
        quitadas = list(acerto.parcelas_quitadas.all())
        self.assertEqual(len(quitadas), 2)  # Uber (4000) + parte abatida do Jantar (4000)
        for p in quitadas:
            self.assertEqual(p.status, Installment.STATUS_PAID)
            self.assertEqual(p.paid_via, Installment.PAID_VIA_COMPENSATION)
        # ...e a partir da parcela dá para ver por qual acerto foi quitada
        uber = Installment.objects.get(pk=self.uber_parcela)
        self.assertEqual(uber.quitacoes_acerto.get().id, acerto.id)

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

    def test_proposta_reversa_bloqueada_e_revisavel(self):
        # vic propõe a byt. Quando byt tenta propor a vic, recebe 409 apontando a
        # proposta existente (para revisar), em vez de criar uma concorrente.
        a = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        b = self.byt.post(ACERTAR, {'para_id': int(self.s.vic_id)}, format='json')
        self.assertEqual(b.status_code, 409, b.content)
        self.assertEqual(b.data['acerto_id'], a.data['id'])
        # só existe uma proposta pendente entre os dois
        self.assertEqual(Acerto.objects.filter(status='pending').count(), 1)

        # byt revisa e confirma a proposta existente → compensação acontece uma vez
        r = self.byt.post(_confirmar(a.data['id']), format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(Debt.objects.filter(description='Acerto de contas').exists())
        # resíduo de 1000 no Jantar
        self.assertEqual(Installment.objects.get(pk=self.s.parcela_byt).amount_cents, 1000)

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

    # ── detalhamento ──────────────────────────────────────────────────────────
    def test_detalhe_itemiza_os_dois_sentidos(self):
        r = self.vic.get(f'{ACERTAR}detalhe/?pessoa={int(self.s.byt_id)}')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['total_recebe'], 5000)  # Jantar (byt deve à vic)
        self.assertEqual(r.data['total_paga'], 4000)    # Uber (vic deve a byt)
        self.assertEqual(r.data['saldo_cents'], 1000)
        self.assertTrue(r.data['compensavel'])
        descr_recebe = {i['descricao'] for i in r.data['voce_recebe']}
        descr_paga = {i['descricao'] for i in r.data['voce_paga']}
        self.assertEqual(descr_recebe, {'Jantar'})
        self.assertEqual(descr_paga, {'Uber'})
        self.assertEqual(r.data['voce_recebe'][0]['grupo'], 'Grupo Vitima')

    def test_detalhe_pessoa_obrigatorio(self):
        r = self.vic.get(f'{ACERTAR}detalhe/')
        self.assertEqual(r.status_code, 400)

    def test_detalhe_requires_auth(self):
        r = self.api().get(f'{ACERTAR}detalhe/?pessoa={int(self.s.byt_id)}')
        self.assertEqual(r.status_code, 401)

    def test_detalhe_por_acerto_mostra_selecao(self):
        prop = self.vic.post(ACERTAR, {
            'para_id': int(self.s.byt_id),
            'parcela_ids': [str(self.uber_parcela), str(self.s.parcela_byt)],
        }, format='json')
        # destinatário (byt) revisa a seleção da proposta
        r = self.byt.get(f"{ACERTAR}detalhe/?acerto={prop.data['id']}")
        self.assertEqual(r.status_code, 200, r.content)
        # da perspectiva de byt: recebe a Uber (byt credor), paga o Jantar (byt devedor)
        self.assertEqual({i['descricao'] for i in r.data['voce_recebe']}, {'Uber'})
        self.assertEqual({i['descricao'] for i in r.data['voce_paga']}, {'Jantar'})

    def test_detalhe_por_acerto_alheio_404(self):
        prop = self.vic.post(ACERTAR, {'para_id': int(self.s.byt_id)}, format='json')
        r = self.api(self.s.mb3_t).get(f"{ACERTAR}detalhe/?acerto={prop.data['id']}")
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
