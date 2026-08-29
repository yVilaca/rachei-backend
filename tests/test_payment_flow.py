"""
Fluxo de pagamento no nível da API: declarar → confirmar / rejeitar, link de
cobrança e página pública. A suíte IDOR já cobre *quem pode* agir; aqui o foco
são as **transições de estado** (idempotência) e a expiração do link público —
onde bugs de app de dinheiro se escondem.

Cenário (build_scenario): victim é credora; byt deve 5000 (Jantar).
"""
from datetime import timedelta

from django.utils import timezone

from apps.debts.models import Installment
from apps.payments.models import ChargeLink
from .helpers import SecurityTestCase


def _comprovante(pk):
    return f'/api/parcelas/{pk}/comprovante/'


def _confirmar(pk):
    return f'/api/parcelas/{pk}/confirmar/'


def _rejeitar(pk):
    return f'/api/parcelas/{pk}/rejeitar/'


def _link(pk):
    return f'/api/parcelas/{pk}/link-cobranca/'


def _publico(token):
    return f'/api/pagamento/{token}/'


class PaymentFlowTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)   # credora
        self.byt = self.api(self.s.byt_t)   # devedora de parcela_byt (5000)
        self.parcela = self.s.parcela_byt

    def _status(self):
        return Installment.objects.get(pk=self.parcela).status

    # ── declarar (devedor) ────────────────────────────────────────────────────
    def test_devedor_declara_muda_para_aguardando(self):
        r = self.byt.post(_comprovante(self.parcela), {}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self._status(), Installment.STATUS_AWAITING)

    def test_apenas_devedor_declara(self):
        # credor não declara pagamento do devedor
        r = self.vic.post(_comprovante(self.parcela), {}, format='json')
        self.assertEqual(r.status_code, 400)
        # outro membro (mb3) também não
        r = self.api(self.s.mb3_t).post(_comprovante(self.parcela), {}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_declarar_parcela_ja_paga_falha(self):
        self.byt.post(_comprovante(self.parcela), {}, format='json')
        self.vic.patch(_confirmar(self.parcela), format='json')  # vira paid
        r = self.byt.post(_comprovante(self.parcela), {}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_declarar_exige_auth(self):
        r = self.api().post(_comprovante(self.parcela), {}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_declarar_parcela_de_outro_grupo_404(self):
        # outsider não é membro do grupo → não enxerga a parcela
        out_t, _ = self.register('outsider')
        r = self.api(out_t).post(_comprovante(self.parcela), {}, format='json')
        self.assertEqual(r.status_code, 404)

    # ── confirmar (credor) ────────────────────────────────────────────────────
    def test_credor_confirma_pagamento(self):
        self.byt.post(_comprovante(self.parcela), {}, format='json')
        r = self.vic.patch(_confirmar(self.parcela), format='json')
        self.assertEqual(r.status_code, 200, r.content)
        parcela = Installment.objects.get(pk=self.parcela)
        self.assertEqual(parcela.status, Installment.STATUS_PAID)
        self.assertEqual(parcela.paid_via, Installment.PAID_VIA_PAYMENT)
        self.assertIsNotNone(parcela.confirmed_at)

    def test_confirmar_sem_estar_aguardando_falha(self):
        # parcela está 'pending' (ninguém declarou) → não pode confirmar
        r = self.vic.patch(_confirmar(self.parcela), format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._status(), Installment.STATUS_PENDING)

    def test_apenas_credor_confirma(self):
        self.byt.post(_comprovante(self.parcela), {}, format='json')
        # devedor não confirma o próprio pagamento
        r = self.byt.patch(_confirmar(self.parcela), format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._status(), Installment.STATUS_AWAITING)

    def test_confirmar_duas_vezes_falha(self):
        self.byt.post(_comprovante(self.parcela), {}, format='json')
        self.vic.patch(_confirmar(self.parcela), format='json')
        r = self.vic.patch(_confirmar(self.parcela), format='json')
        self.assertEqual(r.status_code, 400)  # já não está aguardando

    # ── rejeitar (credor) ─────────────────────────────────────────────────────
    def test_credor_rejeita_volta_para_pendente(self):
        self.byt.post(_comprovante(self.parcela), {}, format='json')
        r = self.vic.post(_rejeitar(self.parcela), format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._status(), Installment.STATUS_PENDING)

    def test_rejeitar_sem_estar_aguardando_falha(self):
        r = self.vic.post(_rejeitar(self.parcela), format='json')
        self.assertEqual(r.status_code, 400)

    def test_apenas_credor_rejeita(self):
        self.byt.post(_comprovante(self.parcela), {}, format='json')
        r = self.byt.post(_rejeitar(self.parcela), format='json')
        self.assertEqual(r.status_code, 400)


class ChargeLinkTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)
        self.byt = self.api(self.s.byt_t)
        self.parcela = self.s.parcela_byt

    def _gerar(self):
        return self.vic.post(_link(self.parcela), format='json')

    def test_credor_gera_link(self):
        r = self._gerar()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn('token', r.data)
        self.assertIn('expires_at', r.data)

    def test_apenas_credor_gera_link(self):
        r = self.byt.post(_link(self.parcela), format='json')
        self.assertEqual(r.status_code, 400)

    def test_gerar_link_de_parcela_paga_falha(self):
        self.byt.post(_comprovante(self.parcela), {}, format='json')
        self.vic.patch(_confirmar(self.parcela), format='json')
        r = self._gerar()
        self.assertEqual(r.status_code, 400)

    def test_regerar_invalida_o_token_antigo(self):
        t1 = self._gerar().data['token']
        t2 = self._gerar().data['token']
        self.assertNotEqual(t1, t2)
        # token antigo foi deletado → página pública não resolve
        self.assertEqual(self.api().get(_publico(t1)).status_code, 404)
        self.assertEqual(self.api().get(_publico(t2)).status_code, 200)


class PublicChargePageTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)
        self.token = self.vic.post(_link(self.s.parcela_byt), format='json').data['token']

    def test_pagina_publica_mostra_a_divida_sem_auth(self):
        r = self.api().get(_publico(self.token))  # sem autenticação
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['descricao'], 'Jantar')

    def test_marca_used_at_de_forma_idempotente(self):
        link = ChargeLink.objects.get(token=self.token)
        self.assertIsNone(link.used_at)
        self.api().get(_publico(self.token))
        primeira = ChargeLink.objects.get(token=self.token).used_at
        self.assertIsNotNone(primeira)
        self.api().get(_publico(self.token))  # revisita não muda o carimbo
        self.assertEqual(ChargeLink.objects.get(token=self.token).used_at, primeira)

    def test_token_inexistente_404(self):
        r = self.api().get(_publico('00000000-0000-0000-0000-000000000000'))
        self.assertEqual(r.status_code, 404)

    def test_link_expirado_nao_resolve(self):
        # Regressão: expires_at (7 dias) deve valer. Link vencido → 404.
        ChargeLink.objects.filter(token=self.token).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        r = self.api().get(_publico(self.token))
        self.assertEqual(r.status_code, 404)
