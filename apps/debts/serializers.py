from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from rest_framework import serializers

from apps.groups.models import ContatoPendente
from apps.users.serializers import UserListSerializer
from .models import Debt, Installment

User = get_user_model()


def debtor_repr(obj):
    """Devedor da parcela: usuário registrado ou contato pendente (flag `pending`).
    Para pendente, o `id` é prefixado ('p<contato_id>') e o telefone nunca é exposto."""
    if obj.debtor_id:
        u = obj.debtor
        return {'id': u.pk, 'name': u.get_full_name() or u.username, 'pending': False}
    c = obj.debtor_contato
    if c:
        return {'id': f'p{c.pk}', 'name': c.name, 'pending': True}
    return None


class ParcelaBalanceSerializer(serializers.ModelSerializer):
    """Campos mínimos para listagem — cálculo de saldo e filtro de status."""
    debtor = serializers.SerializerMethodField()

    class Meta:
        model = Installment
        fields = ('id', 'debtor', 'amount_cents', 'status')

    def get_debtor(self, obj):
        return debtor_repr(obj)


class ParcelaListSerializer(serializers.ModelSerializer):
    """Campos completos para detalhe de despesa."""
    debtor = serializers.SerializerMethodField()
    comprovante = serializers.SerializerMethodField()
    charge_link_token = serializers.SerializerMethodField()

    class Meta:
        model = Installment
        fields = (
            'id', 'debtor', 'amount_cents', 'status', 'paid_via',
            'paid_at', 'confirmed_at', 'comprovante', 'charge_link_token',
        )

    def get_debtor(self, obj):
        return debtor_repr(obj)

    def get_comprovante(self, obj):
        cpv = sorted(obj.comprovantes.all(), key=lambda c: c.uploaded_at, reverse=True)
        if not cpv:
            return None
        c = cpv[0]
        # Arquivo servido por endpoint autenticado; file_url é legado.
        url = reverse('payments:comprovante-arquivo', args=[c.id]) if c.arquivo else c.file_url
        return {'id': str(c.id), 'file_url': url, 'uploaded_at': c.uploaded_at}

    def get_charge_link_token(self, obj):
        try:
            return str(obj.charge_link.token)
        except ObjectDoesNotExist:
            return None


# ParcelaDetailSerializer mantido para GET /api/parcelas/{id}/ — sem alterações
ParcelaDetailSerializer = ParcelaListSerializer


class DespesaListSerializer(serializers.ModelSerializer):
    """Campos para listagem por grupo — inclui parcelas mínimas para saldo e filtros."""
    paid_by = UserListSerializer(read_only=True)
    parcelas = ParcelaBalanceSerializer(source='installments', many=True, read_only=True)

    class Meta:
        model = Debt
        fields = (
            'id', 'group_id', 'description', 'total_amount_cents',
            'split_type', 'paid_by', 'created_at', 'parcelas',
        )


class DespesaDetailSerializer(serializers.ModelSerializer):
    """Detalhe completo com parcelas aninhadas."""
    paid_by = UserListSerializer(read_only=True)
    group_name = serializers.CharField(source='group.name', read_only=True)
    parcelas = ParcelaListSerializer(source='installments', many=True, read_only=True)
    editavel = serializers.SerializerMethodField()

    class Meta:
        model = Debt
        fields = (
            'id', 'group_id', 'group_name', 'description', 'total_amount_cents',
            'split_type', 'paid_by', 'created_at', 'parcelas', 'editavel',
        )

    def get_editavel(self, obj):
        """Valores/exclusão liberados só se ninguém (fora o credor) saiu de pendente."""
        return all(
            inst.status == Installment.STATUS_PENDING
            for inst in obj.installments.all()
            if inst.debtor_id != obj.paid_by_id
        )


class ParcelaInputSerializer(serializers.Serializer):
    """Entrada de uma parcela — devedor registrado OU contato pendente (exatamente um)."""
    debtor_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='debtor', required=False, allow_null=True)
    debtor_contato_id = serializers.PrimaryKeyRelatedField(
        queryset=ContatoPendente.objects.all(), source='debtor_contato', required=False, allow_null=True)
    amount_cents = serializers.IntegerField(min_value=1)

    def validate(self, data):
        has_user = data.get('debtor') is not None
        has_contato = data.get('debtor_contato') is not None
        if has_user == has_contato:
            raise serializers.ValidationError('Cada parcela precisa de um devedor (usuário ou contato pendente).')
        return data


class DespesaFormSerializer(serializers.Serializer):
    """Validação de criação de despesa com parcelas.

    O credor (paid_by) é sempre request.user — nunca vem do corpo.
    Quem registra a despesa é quem bancou a conta e confirmará os pagamentos.
    """
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


class DespesaEditSerializer(serializers.Serializer):
    """
    Edição de despesa. `description` sempre; valores/divisão/parcelas são
    opcionais — enviados juntos apenas quando a dívida ainda é alterável.
    """
    description = serializers.CharField(max_length=255)
    total_amount_cents = serializers.IntegerField(min_value=1, required=False)
    split_type = serializers.ChoiceField(choices=Debt.SPLIT_CHOICES, required=False)
    parcelas = ParcelaInputSerializer(many=True, required=False)

    def validate(self, data):
        parcelas = data.get('parcelas')
        if parcelas is not None:
            if not parcelas:
                raise serializers.ValidationError({'parcelas': 'Informe ao menos uma parcela.'})
            if data.get('total_amount_cents') is None or data.get('split_type') is None:
                raise serializers.ValidationError(
                    'Para alterar valores, envie total_amount_cents e split_type.'
                )
            if data['split_type'] == Debt.SPLIT_CUSTOM:
                soma = sum(p['amount_cents'] for p in parcelas)
                if soma != data['total_amount_cents']:
                    raise serializers.ValidationError(
                        {'parcelas': 'Soma das parcelas não confere com o total da despesa.'}
                    )
        return data
