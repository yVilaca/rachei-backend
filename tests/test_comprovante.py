"""
Comprovante de pagamento: upload real (arquivo em disco) e serviço AUTENTICADO
do arquivo (nunca por URL pública). Antes, o front mandava um blob URL efêmero
e o campo era URLField → 400; e o credor nunca via a imagem.
"""
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.debts.models import Installment
from apps.payments.models import Comprovante
from .helpers import SecurityTestCase

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 64  # cabeçalho PNG + corpo


def _comprovante(pk):
    return f'/api/parcelas/{pk}/comprovante/'


def _arquivo(cpv_id):
    return f'/api/comprovantes/{cpv_id}/arquivo/'


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ComprovanteUploadTest(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.build_scenario()
        self.vic = self.api(self.s.vic_t)   # credora
        self.byt = self.api(self.s.byt_t)   # devedora
        self.parcela = self.s.parcela_byt

    def _upload(self, client=None, name='recibo.png', content=PNG, ctype='image/png'):
        f = SimpleUploadedFile(name, content, content_type=ctype)
        return (client or self.byt).post(
            _comprovante(self.parcela), {'arquivo': f}, format='multipart',
        )

    def test_devedor_envia_arquivo_e_parcela_fica_aguardando(self):
        r = self._upload()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Installment.objects.get(pk=self.parcela).status, Installment.STATUS_AWAITING)
        cpv = Comprovante.objects.get()
        self.assertTrue(cpv.arquivo)  # arquivo realmente armazenado
        # a URL servida é o endpoint autenticado, não uma mídia pública
        self.assertEqual(r.data['file_url'], _arquivo(cpv.id))

    def test_credor_baixa_o_arquivo(self):
        cpv_id = self._upload().data['id']
        r = self.vic.get(_arquivo(cpv_id))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), PNG)  # conteúdo íntegro

    def test_devedor_tambem_baixa(self):
        cpv_id = self._upload().data['id']
        self.assertEqual(self.byt.get(_arquivo(cpv_id)).status_code, 200)

    def test_terceiro_do_grupo_nao_baixa(self):
        # mb3 é membro do grupo mas não é parte da parcela → 404 (não vaza)
        cpv_id = self._upload().data['id']
        self.assertEqual(self.api(self.s.mb3_t).get(_arquivo(cpv_id)).status_code, 404)

    def test_arquivo_exige_auth(self):
        cpv_id = self._upload().data['id']
        self.assertEqual(self.api().get(_arquivo(cpv_id)).status_code, 401)

    def test_tipo_invalido_recusado(self):
        r = self._upload(name='malware.txt', content=b'x', ctype='text/plain')
        self.assertEqual(r.status_code, 400)

    def test_declarar_sem_arquivo_ainda_funciona(self):
        # comprovante é opcional: declarar sem anexo continua válido
        r = self.byt.post(_comprovante(self.parcela), {}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Installment.objects.get(pk=self.parcela).status, Installment.STATUS_AWAITING)
