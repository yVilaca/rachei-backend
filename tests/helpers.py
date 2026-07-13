"""
Helpers para a suíte de regressão de segurança (autorização / JWT / throttles).

Regras (herdadas da auditoria manual):
- Toda conta é criada via /register e autenticada via /login REAIS — nunca
  fixture direta de usuário "perfeito" pulando o fluxo de auth.
- O único atalho de fixture é marcar phone_verified=True (canal SMS OTP é
  impraticável em teste); isso NÃO pula autenticação — apenas o side-channel
  de verificação de telefone, necessário para add-member resolver membro ativo.
- Cada teste roda em banco SQLite em memória, efêmero (manage.py test).
"""
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase, APIClient

User = get_user_model()

# Chave Fernet pública de teste (mesma usada em apps/users/tests.py)
TEST_ENCRYPTION_KEY = 'YNqvfjrYdzvwqJQQiHQCV_-2eeWNfya4UAHsxiNdNwU='

# Senha que passa em todos os validators (não numérica, não comum, não similar ao email)
STRONG_PWD = 'Zx9kLmnQ7er'

PHONES = {
    'attacker': '+5599900000001',
    'victim': '+5599900000002',
    'bystander': '+5599900000003',
    'member3': '+5599900000004',
    'outsider': '+5599900000005',
}


class SecurityTestCase(APITestCase):
    """Base: isola throttles (cache) e oferece auth real + cenário padrão."""

    def setUp(self):
        cache.clear()  # throttles do DRF vivem no cache; isola cada teste
        self.addCleanup(cache.clear)

    # ── auth real ──────────────────────────────────────────────────────────
    def register(self, tag, phone=None):
        """Cria conta via /register real. Retorna (access_token, user_id)."""
        c = APIClient()
        r = c.post('/api/auth/register/', {
            'name': f'User {tag}',
            'email': f'{tag}@example.invalid',
            'phone': phone or PHONES.get(tag, '+5599900009999'),
            'password': STRONG_PWD,
        }, format='json')
        assert r.status_code == 201, f'register {tag} falhou: {r.status_code} {r.content}'
        return r.data['access'], r.data['user']['id']

    def login(self, tag):
        """Login real. Retorna o Response (para inspecionar access/cookie/2fa)."""
        c = APIClient()
        return c.post('/api/auth/login/', {
            'email': f'{tag}@example.invalid',
            'password': STRONG_PWD,
        }, format='json')

    def api(self, token=None):
        """APIClient novo, opcionalmente autenticado como o portador do token."""
        c = APIClient()
        if token:
            c.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        return c

    # ── cenário padrão (grupo + dívida) ──────────────────────────────────────
    def build_scenario(self):
        """
        victim = admin/credor; bystander e member3 = membros ativos/devedores;
        attacker e outsider = fora do grupo. Cria uma dívida (victim credor).
        Retorna SimpleNamespace com tokens, ids e recursos.
        """
        atk_t, atk_id = self.register('attacker')
        vic_t, vic_id = self.register('victim')
        byt_t, byt_id = self.register('bystander')
        mb3_t, mb3_id = self.register('member3')

        # Verifica telefones (side-channel SMS) para add-member resolver membro ativo
        User.objects.filter(
            email__in=[f'{t}@example.invalid' for t in ('victim', 'bystander', 'member3', 'attacker')]
        ).update(phone_verified=True)

        vic = self.api(vic_t)
        g = vic.post('/api/grupos/', {'name': 'Grupo Vitima'}, format='json')
        assert g.status_code == 201, g.content
        group_id = g.data['id']

        vic.post(f'/api/grupos/{group_id}/membros/', {'phone': PHONES['bystander']}, format='json')
        vic.post(f'/api/grupos/{group_id}/membros/', {'phone': PHONES['member3']}, format='json')

        members = vic.get(f'/api/grupos/{group_id}/membros/').data
        mlist = members['results'] if isinstance(members, dict) and 'results' in members else members
        byt_member_pk = next(
            (m['id'] for m in mlist if m.get('user') and str(m['user']['id']) == str(byt_id)), None
        )

        d = vic.post('/api/despesas/', {
            'grupo_id': group_id,
            'description': 'Jantar',
            'total_amount_cents': 10000,
            'split_type': 'custom',
            'parcelas': [
                {'debtor_id': int(byt_id), 'amount_cents': 5000},
                {'debtor_id': int(mb3_id), 'amount_cents': 5000},
            ],
        }, format='json')
        assert d.status_code == 201, d.content
        debt_id = d.data['id']
        parc = {str(p['debtor']['id']): p['id'] for p in d.data['parcelas']}

        # grupo do próprio atacante (para tentativas de mover recurso p/ escopo dele)
        atk = self.api(atk_t)
        User.objects.filter(email='attacker@example.invalid').update(phone_verified=True)
        ga = atk.post('/api/grupos/', {'name': 'Grupo Atacante'}, format='json')
        atk_group_id = ga.data['id']

        return SimpleNamespace(
            atk_t=atk_t, atk_id=atk_id,
            vic_t=vic_t, vic_id=vic_id,
            byt_t=byt_t, byt_id=byt_id,
            mb3_t=mb3_t, mb3_id=mb3_id,
            group_id=group_id, debt_id=debt_id,
            parcela_byt=parc[str(byt_id)], parcela_mb3=parc[str(mb3_id)],
            byt_member_pk=byt_member_pk,
            atk_group_id=atk_group_id,
        )
