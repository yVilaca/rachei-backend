from rest_framework import serializers

from apps.users.serializers import UserListSerializer
from .models import ChargeLink, Comprovante


class ComprovanteFormSerializer(serializers.ModelSerializer):
    """Input para upload de comprovante."""

    class Meta:
        model = Comprovante
        fields = ('file_url',)


class ComprovanteDetailSerializer(serializers.ModelSerializer):
    uploaded_by = UserListSerializer(read_only=True)

    class Meta:
        model = Comprovante
        fields = ('id', 'file_url', 'uploaded_by', 'uploaded_at')


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
