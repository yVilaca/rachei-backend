from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserListSerializer(serializers.ModelSerializer):
    """Campos mínimos — usado como nested em outros serializers."""
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'name', 'avatar_url')

    def get_name(self, obj):
        return obj.get_full_name() or obj.username


class UserDetailSerializer(serializers.ModelSerializer):
    """Perfil completo do usuário autenticado."""
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'name', 'email', 'phone', 'avatar_url', 'plan',
            'notif_cobracas', 'notif_confirmacoes', 'notif_lembretes',
            'date_joined',
        )
        read_only_fields = ('id', 'plan', 'date_joined')

    def get_name(self, obj):
        return obj.get_full_name() or obj.username


class UserFormSerializer(serializers.ModelSerializer):
    """Atualização de perfil — apenas campos editáveis."""

    class Meta:
        model = User
        fields = ('phone', 'avatar_url', 'notif_cobracas', 'notif_confirmacoes', 'notif_lembretes')


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login: adiciona claim 'plan' no JWT e retorna dados do usuário na resposta."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['plan'] = user.plan
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserDetailSerializer(self.user).data
        return data


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('Email já cadastrado.')
        return value

    def create(self, validated_data):
        parts = validated_data['name'].strip().split(' ', 1)
        return User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=parts[0],
            last_name=parts[1] if len(parts) > 1 else '',
        )
