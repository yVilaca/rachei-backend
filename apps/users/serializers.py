import hashlib
import re

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import TrustedDevice, TwoFactorConfig
from .tokens import TwoFAPendingToken

User = get_user_model()


class UserListSerializer(serializers.ModelSerializer):
    """Campos mínimos — usado como nested em outros serializers."""
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'name')

    def get_name(self, obj):
        return obj.get_full_name() or obj.username


class UserDetailSerializer(serializers.ModelSerializer):
    """Perfil completo do usuário autenticado."""
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'name', 'email', 'phone', 'phone_verified', 'avatar_url', 'plan',
            'notif_cobracas', 'notif_confirmacoes', 'notif_lembretes',
            'date_joined',
        )
        read_only_fields = ('id', 'plan', 'date_joined', 'phone_verified')

    def get_name(self, obj):
        return obj.get_full_name() or obj.username


class UserFormSerializer(serializers.ModelSerializer):
    """Atualização de perfil — apenas campos editáveis (phone excluído: requer re-verificação)."""

    class Meta:
        model = User
        fields = ('avatar_url', 'notif_cobracas', 'notif_confirmacoes', 'notif_lembretes')


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login: verifica 2FA antes de emitir tokens, adiciona claim 'plan'."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['plan'] = user.plan
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user

        # Verifica se o usuário tem 2FA ativo
        config = TwoFactorConfig.objects.filter(user=user, is_active=True).first()
        if not config:
            data['user'] = UserDetailSerializer(user).data
            return data

        # Verifica dispositivo confiável
        trusted_token = (self.context.get('request').data.get('trusted_device_token') or '').strip()
        if trusted_token:
            token_hash = hashlib.sha256(trusted_token.encode()).hexdigest()
            td = TrustedDevice.objects.filter(
                user=user,
                token_hash=token_hash,
                expires_at__gt=timezone.now(),
            ).first()
            is_trusted = td is not None
            if is_trusted:
                # Registra último uso do dispositivo
                TrustedDevice.objects.filter(pk=td.pk).update(last_used_at=timezone.now())
                data['user'] = UserDetailSerializer(user).data
                return data

        # 2FA necessário — invalida o refresh token que acabou de ser criado
        try:
            RefreshToken(data['refresh']).blacklist()
        except Exception:
            pass

        pending = TwoFAPendingToken()
        pending['user_id'] = user.pk
        return {'requires_2fa': True, 'pending_token': str(pending)}


_E164_RE = re.compile(r'^\+\d{8,15}$')


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('Email já cadastrado.')
        return value

    def validate_phone(self, value):
        value = value.strip()
        if not _E164_RE.match(value):
            raise serializers.ValidationError(
                'Telefone deve estar no formato E.164 (ex: +5511999999999).'
            )
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError('Telefone já cadastrado.')
        return value

    def create(self, validated_data):
        parts = validated_data['name'].strip().split(' ', 1)
        return User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            phone=validated_data['phone'],
            phone_verified=False,
            first_name=parts[0],
            last_name=parts[1] if len(parts) > 1 else '',
        )
