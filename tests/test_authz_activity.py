"""
Segurança dos endpoints de atividade / notificações.

Invariantes exigidas:
- Cada usuário só vê eventos DERIVADOS dos próprios débitos/parcelas.
- Endpoint é somente leitura (GET). Não há criação de notificação pelo cliente.
- marcar-lida é escopado ao request.user: um usuário não altera o estado
  de leitura de outro nem injeta notificação visível a terceiros.
- Sem autenticação: 401.
"""
from .helpers import SecurityTestCase

ATIVIDADE = '/api/atividade/'
MARCAR = '/api/atividade/marcar-lida/'


def _ids(resp):
    return [e['id'] for e in resp.data['results']]


def _despesa_ids(resp):
    return {e['despesa_id'] for e in resp.data['results']}


class ActivityScopingTest(SecurityTestCase):
    """Cada feed contém apenas eventos dos próprios recursos."""

    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()

    def test_outsider_feed_has_no_foreign_events(self):
        # attacker não participa da dívida da vítima
        resp = self.api(self.s.atk_t).get(ATIVIDADE)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.s.debt_id, _despesa_ids(resp),
                         'feed do atacante vazou dívida alheia')

    def test_creditor_sees_own_created_debt(self):
        resp = self.api(self.s.vic_t).get(ATIVIDADE)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f'ev-created-{self.s.debt_id}', _ids(resp))
        self.assertIn(self.s.debt_id, _despesa_ids(resp))

    def test_debtor_sees_own_pending_event(self):
        resp = self.api(self.s.byt_t).get(ATIVIDADE)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f'ev-pending-{self.s.parcela_byt}', _ids(resp))

    def test_debtor_does_not_see_other_debtors_installment(self):
        # bystander não deve ver o evento de parcela do member3
        resp = self.api(self.s.byt_t).get(ATIVIDADE)
        self.assertNotIn(f'ev-pending-{self.s.parcela_mb3}', _ids(resp))


class ActivityReadOnlyTest(SecurityTestCase):
    """Feed é somente leitura: cliente não cria/edita/apaga eventos."""

    def setUp(self):
        super().setUp()
        self.tok, _ = self.register('victim')

    def test_post_list_not_allowed(self):
        self.assertEqual(self.api(self.tok).post(ATIVIDADE, {}, format='json').status_code, 405)

    def test_put_list_not_allowed(self):
        self.assertEqual(self.api(self.tok).put(ATIVIDADE, {}, format='json').status_code, 405)

    def test_patch_list_not_allowed(self):
        self.assertEqual(self.api(self.tok).patch(ATIVIDADE, {}, format='json').status_code, 405)

    def test_delete_list_not_allowed(self):
        self.assertEqual(self.api(self.tok).delete(ATIVIDADE).status_code, 405)

    def test_get_marcar_lida_not_allowed(self):
        self.assertEqual(self.api(self.tok).get(MARCAR).status_code, 405)


class MarcarLidaScopeTest(SecurityTestCase):
    """marcar-lida afeta somente o próprio usuário e nunca cria eventos."""

    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()

    def test_marking_read_is_per_user(self):
        byt_event = f'ev-pending-{self.s.parcela_byt}'
        # attacker tenta marcar como lido um evento do bystander
        r = self.api(self.s.atk_t).post(MARCAR, {'evento_ids': [byt_event]}, format='json')
        self.assertEqual(r.status_code, 200)
        # o feed do bystander continua com aquele evento NÃO lido
        feed = self.api(self.s.byt_t).get(ATIVIDADE)
        ev = next(e for e in feed.data['results'] if e['id'] == byt_event)
        self.assertFalse(ev['lido'], 'estado de leitura de um usuário foi alterado por outro')

    def test_marking_read_does_not_create_events_for_anyone(self):
        # attacker marca ids arbitrários; não pode surgir evento no feed de ninguém
        self.api(self.s.atk_t).post(MARCAR, {'evento_ids': ['ev-fake-1', 'ev-fake-2']}, format='json')
        atk_feed = self.api(self.s.atk_t).get(ATIVIDADE)
        self.assertEqual(atk_feed.data['results'], [], 'marcar-lida injetou evento no feed')
        byt_feed = self.api(self.s.byt_t).get(ATIVIDADE)
        self.assertNotIn('ev-fake-1', _ids(byt_feed))

    def test_owner_marks_own_event_read(self):
        before = self.api(self.s.vic_t).get(ATIVIDADE)
        target = f'ev-created-{self.s.debt_id}'
        self.assertIn(target, _ids(before))
        unread_before = before.data['unread_count']

        r = self.api(self.s.vic_t).post(MARCAR, {'evento_ids': [target]}, format='json')
        self.assertEqual(r.status_code, 200)

        after = self.api(self.s.vic_t).get(ATIVIDADE)
        ev = next(e for e in after.data['results'] if e['id'] == target)
        self.assertTrue(ev['lido'])
        self.assertEqual(after.data['unread_count'], unread_before - 1)


class MarcarLidaValidationTest(SecurityTestCase):
    """Validação de entrada do marcar-lida."""

    def setUp(self):
        super().setUp()
        self.tok, _ = self.register('victim')

    def test_non_list_rejected(self):
        r = self.api(self.tok).post(MARCAR, {'evento_ids': 'nao-e-lista'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_too_many_ids_rejected(self):
        r = self.api(self.tok).post(MARCAR, {'evento_ids': [f'ev-{i}' for i in range(51)]}, format='json')
        self.assertEqual(r.status_code, 400)


class ActivityUnauthenticatedTest(SecurityTestCase):
    """Sem token: 401 em ambos os endpoints."""

    def test_list_requires_auth(self):
        self.assertEqual(self.api().get(ATIVIDADE).status_code, 401)

    def test_marcar_requires_auth(self):
        self.assertEqual(self.api().post(MARCAR, {'evento_ids': []}, format='json').status_code, 401)
