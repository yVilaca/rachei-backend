from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from users.serializers import UserListSerializer
from .models import Debt, Installment

User = get_user_model()


class ParcelaListSerializer(serializers.ModelSerializer):
    """Campos mínimos para listagem dentro de uma despesa."""
    debtor = UserListSerializer(read_only=True)

    class Meta:
        model = Installment
        fields = ('id', 'debtor', 'amount_cents', 'status', 'paid_at', 'confirmed_at')


class ParcelaDetailSerializer(serializers.ModelSerializer):
    """Detalhe de parcela com comprovante e token do link."""
    debtor = UserListSerializer(read_only=True)
    comprovante = serializers.SerializerMethodField()
    charge_link_token = serializers.SerializerMethodField()

    class Meta:
        model = Installment
        fields = (
            'id', 'debtor', 'amount_cents', 'status',
            'paid_at', 'confirmed_at', 'comprovante', 'charge_link_token',
        )

    def get_comprovante(self, obj):
        cpv = sorted(obj.comprovantes.all(), key=lambda c: c.uploaded_at, reverse=True)
        if not cpv:
            return None
        c = cpv[0]
        return {'id': str(c.id), 'file_url': c.file_url, 'uploaded_at': c.uploaded_at}

    def get_charge_link_token(self, obj):
        try:
            return str(obj.charge_link.token)
        except ObjectDoesNotExist:
            return None


class DespesaListSerializer(serializers.ModelSerializer):
    """Campos mínimos para listagem — card de despesa."""
    paid_by = UserListSerializer(read_only=True)

    class Meta:
        model = Debt
        fields = ('id', 'description', 'total_amount_cents', 'split_type', 'paid_by', 'created_at')


class DespesaDetailSerializer(serializers.ModelSerializer):
    """Detalhe completo com parcelas aninhadas."""
    paid_by = UserListSerializer(read_only=True)
    created_by = UserListSerializer(read_only=True)
    parcelas = ParcelaListSerializer(source='installments', many=True, read_only=True)

    class Meta:
        model = Debt
        fields = (
            'id', 'description', 'total_amount_cents', 'split_type',
            'paid_by', 'created_by', 'created_at', 'parcelas',
        )


class ParcelaInputSerializer(serializers.Serializer):
    """Entrada de uma parcela ao criar despesa."""
    debtor_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), source='debtor')
    amount_cents = serializers.IntegerField(min_value=1)


class DespesaFormSerializer(serializers.Serializer):
    """Validação de criação de despesa com parcelas."""
    grupo_id = serializers.UUIDField()
    description = serializers.CharField(max_length=255)
    total_amount_cents = serializers.IntegerField(min_value=1)
    split_type = serializers.ChoiceField(choices=Debt.SPLIT_CHOICES)
    parcelas = ParcelaInputSerializer(many=True)

    def validate_parcelas(self, value):
        if not value:
            raise serializers.ValidationError('Informe ao menos uma parcela.')
        return value

    def validate(self, data):
        if data['split_type'] == Debt.SPLIT_CUSTOM:
            soma = sum(p['amount_cents'] for p in data['parcelas'])
            if soma != data['total_amount_cents']:
                raise serializers.ValidationError(
                    {'parcelas': 'Soma das parcelas não confere com o total da despesa.'}
                )
        return data
