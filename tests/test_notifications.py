"""
Notificações ativas (e-mail/WhatsApp).

Cobre: gating por preferência do perfil, seleção de canal (WhatsApp só com
telefone verificado), disparo por evento e idempotência dos lembretes.

Roda com NOTIFICACOES_SINCRONAS=True (settings_test) — envios acontecem na
hora e são capturados em mail.outbox e whatsapp_outbox.
"""
from datetime import timedelta

from django.core import mail
from django.test import override_settings
from django.utils import timezone

from apps.debts.models import Debt, Installment
from apps.groups import whatsapp
from apps.notifications import events as notif
from apps.notifications.service import notificar
from .helpers import SecurityTestCase


def _wa():
    return whatsapp.whatsapp_outbox


class NotifBaseTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        mail.outbox.clear()
        whatsapp.whatsapp_outbox.clear()
        self.addCleanup(mail.outbox.clear)
        self.addCleanup(whatsapp.whatsapp_outbox.clear)


class DispatchTest(NotifBaseTest):
    def _user(self, **flags):
        from django.contrib.auth import get_user_model
        _, uid = self.register('victim')  # fluxo real de cadastro
        u = get_user_model().objects.get(pk=uid)
        u.phone_verified = flags.get('phone_verified', True)
        u.notif_cobracas = flags.get('notif_cobracas', True)
        u.notif_confirmacoes = flags.get('notif_confirmacoes', True)
        u.notif_lembretes = flags.get('notif_lembretes', True)
        u.save()
        return u

    def test_envia_email_e_whatsapp(self):
        u = self._user()
        notificar(user=u, categoria='cobrancas', assunto='A', corpo='B')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(_wa()), 1)

    def test_preferencia_desligada_suprime(self):
        u = self._user(notif_cobracas=False)
        notificar(user=u, categoria='cobrancas', assunto='A', corpo='B')
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(_wa()), 0)

    def test_preferencia_e_por_categoria(self):
        # desliga só confirmações; cobranças ainda passa
        u = self._user(notif_confirmacoes=False)
        notificar(user=u, categoria='cobrancas', assunto='A', corpo='B')
        notificar(user=u, categoria='confirmacoes', assunto='C', corpo='D')
        self.assertEqual(len(mail.outbox), 1)  # só a de cobranças

    def test_whatsapp_exige_telefone_verificado(self):
        u = self._user(phone_verified=False)
        notificar(user=u, categoria='cobrancas', assunto='A', corpo='B')
        self.assertEqual(len(mail.outbox), 1)  # e-mail vai
        self.assertEqual(len(_wa()), 0)        # WhatsApp não

    def test_respeita_canais_do_evento(self):
        u = self._user()
        notificar(user=u, categoria='confirmacoes', assunto='A', corpo='B', canais=('email',))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(_wa()), 0)


class EventosTest(NotifBaseTest):
    """Cada evento da matriz dispara para quem deve e pelos canais certos."""

    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        from django.contrib.auth import get_user_model
        self.User = get_user_model()

    def _u(self, uid):
        return self.User.objects.get(pk=uid)

    def test_incluido_em_divida(self):
        notif.incluido_em_divida(
            devedor=self._u(self.s.byt_id), credor=self._u(self.s.vic_id),
            descricao='Jantar', grupo_nome='Praia', valor_cents=5000,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(_wa()), 1)
        self.assertIn('5000', ''.join(m.body for m in mail.outbox).replace(',', '').replace('.', '') or '')

    def test_cobranca_so_whatsapp(self):
        notif.cobranca_enviada(
            devedor=self._u(self.s.byt_id), credor=self._u(self.s.vic_id),
            descricao='Jantar', valor_cents=5000,
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(_wa()), 1)

    def test_pagamento_confirmado_so_email(self):
        notif.pagamento_confirmado(
            devedor=self._u(self.s.byt_id), credor=self._u(self.s.vic_id),
            descricao='Jantar', valor_cents=5000,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(_wa()), 0)


class TriggerIntegracaoTest(NotifBaseTest):
    """Fluxo real: criar despesa dispara notificação ao devedor (via on_commit)."""

    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()

    def test_criar_despesa_notifica_devedores(self):
        vic = self.api(self.s.vic_t)
        with self.captureOnCommitCallbacks(execute=True):
            r = vic.post('/api/despesas/', {
                'grupo_id': self.s.group_id, 'description': 'Churrasco',
                'total_amount_cents': 6000, 'split_type': 'custom',
                'parcelas': [{'debtor_id': int(self.s.byt_id), 'amount_cents': 6000}],
            }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        # devedor (bystander) recebe; credor (vitima) não é notificado
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Churrasco', mail.outbox[0].subject)


@override_settings(LEMBRETE_APOS_DIAS=3, LEMBRETE_INTERVALO_DIAS=4)
class LembretesTest(NotifBaseTest):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        # Isola: quita a parcela do mb3 para sobrar só o bystander pendente na dívida.
        Installment.objects.filter(pk=self.s.parcela_mb3).update(status=Installment.STATUS_PAID)
        # a parcela do bystander (deve 5000 à vítima) é a alvo dos lembretes
        self.parcela = Installment.objects.get(pk=self.s.parcela_byt)

    def _envelhecer(self, dias):
        """Move a data de criação da dívida para `dias` atrás."""
        Debt.objects.filter(pk=self.parcela.debt_id).update(
            created_at=timezone.now() - timedelta(days=dias)
        )

    def _rodar(self):
        from django.core.management import call_command
        call_command('enviar_lembretes')

    def test_nao_lembra_dentro_do_prazo(self):
        self._envelhecer(1)  # só 1 dia < 3
        self._rodar()
        self.assertEqual(len(_wa()), 0)

    def test_lembra_apos_prazo(self):
        self._envelhecer(5)
        self._rodar()
        self.assertEqual(len(_wa()), 1)
        self.parcela.refresh_from_db()
        self.assertIsNotNone(self.parcela.ultimo_lembrete_em)

    def test_idempotente_nao_reenvia_no_mesmo_dia(self):
        self._envelhecer(5)
        self._rodar()
        self._rodar()  # segunda execução imediata não deve reenviar
        self.assertEqual(len(_wa()), 1)

    def test_reenvia_apos_intervalo(self):
        self._envelhecer(5)
        self._rodar()
        self.assertEqual(len(_wa()), 1)
        # simula último lembrete há 5 dias (> intervalo de 4) → reenvia
        Installment.objects.filter(pk=self.parcela.pk).update(
            ultimo_lembrete_em=timezone.now() - timedelta(days=5)
        )
        self._rodar()
        self.assertEqual(len(_wa()), 2)

    def test_nao_lembra_parcela_paga(self):
        self._envelhecer(5)
        Installment.objects.filter(pk=self.parcela.pk).update(status=Installment.STATUS_PAID)
        self._rodar()
        self.assertEqual(len(_wa()), 0)

    def test_lembrete_respeita_preferencia(self):
        self._envelhecer(5)
        from django.contrib.auth import get_user_model
        get_user_model().objects.filter(pk=self.s.byt_id).update(notif_lembretes=False)
        self._rodar()
        self.assertEqual(len(_wa()), 0)
