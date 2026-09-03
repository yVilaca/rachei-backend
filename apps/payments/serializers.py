from django.conf import settings
from django.urls import reverse
from rest_framework import serializers

from apps.users.serializers import UserListSerializer
from .models import ChargeLink, Comprovante

# Tipos aceitos de comprovante (imagem ou PDF).
COMPROVANTE_TIPOS = {'image/jpeg', 'image/png', 'image/webp', 'application/pdf'}


class DeclaracaoPagamentoSerializer(serializers.Serializer):
    """Input para declaração de pagamento — comprovante (arquivo) opcional."""
    arquivo = serializers.FileField(required=False, allow_null=True)

    def validate_arquivo(self, f):
        if f is None:
            return f
        if f.size > settings.COMPROVANTE_MAX_BYTES:
            raise serializers.ValidationError('Arquivo muito grande (máximo 5 MB).')
        content_type = getattr(f, 'content_type', '') or ''
        if content_type not in COMPROVANTE_TIPOS:
            raise serializers.ValidationError('Envie uma imagem (JPG/PNG/WebP) ou PDF.')
        return f


def _comprovante_url(comprovante):
    """URL do endpoint autenticado que serve o arquivo (ou o legado file_url)."""
    if comprovante.arquivo:
        return reverse('payments:comprovante-arquivo', args=[comprovante.id])
    return comprovante.file_url


class ComprovanteDetailSerializer(serializers.ModelSerializer):
    uploaded_by = UserListSerializer(read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Comprovante
        fields = ('id', 'file_url', 'uploaded_by', 'uploaded_at')

    def get_file_url(self, obj):
        return _comprovante_url(obj)


class PagamentoPublicoSerializer(serializers.ModelSerializer):
    """
    Dados da página pública de cobrança — sem informações sensíveis.
    Expõe apenas o suficiente para o devedor reconhecer e pagar a parcela.
    """
    devedor = UserListSerializer(source='installment.debtor', read_only=True)
    credor = UserListSerializer(source='installment.debt.paid_by', read_only=True)
    descricao = serializers.CharField(source='installment.debt.description', read_only=True)
    valor_centavos = serializers.IntegerField(source='installment.amount_cents', read_only=True)
    status_parcela = serializers.CharField(source='installment.status', read_only=True)
    expirado = serializers.SerializerMethodField()

    class Meta:
        model = ChargeLink
        fields = (
            'token', 'devedor', 'credor', 'descricao',
            'valor_centavos', 'status_parcela', 'expires_at', 'expirado',
        )

    def get_expirado(self, obj):
        return obj.is_expired
