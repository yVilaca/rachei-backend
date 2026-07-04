import hashlib
import secrets
from datetime import timedelta

import pyotp
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView as BaseTokenObtainPairView

from .models import PasswordResetCode, TrustedDevice, TwoFactorConfig, generate_backup_codes
from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserDetailSerializer,
    UserFormSerializer,
)
from .throttles import AuthRateThrottle
from .tokens import TwoFAPendingToken

_NEUTRAL_FORGOT = 'Se esse e-mail estiver cadastrado, você receberá um código em breve.'
_INVALID_CODE = {'code': ['Código inválido ou expirado.']}

User = get_user_model()


class CustomTokenObtainPairView(BaseTokenObtainPairView):
    """POST /api/auth/login/ — autentica e retorna tokens + dados do usuário."""
    throttle_classes = [AuthRateThrottle]
    serializer_class = CustomTokenObtainPairSerializer


class RegisterView(generics.CreateAPIView):
    """POST /api/auth/register/ — cria conta e retorna tokens JWT."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthRateThrottle]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        refresh['plan'] = user.plan
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserDetailSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


class LogoutView(APIView):
    """POST /api/auth/logout/ — invalida o refresh token (blacklist)."""

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            raise ValidationError({'refresh': 'Campo obrigatório.'})
        try:
            token = RefreshToken(refresh_token)
            if token.payload.get('user_id') != request.user.id:
                raise ValidationError({'refresh': 'Token não pertence ao usuário autenticado.'})
            token.blacklist()
        except TokenError:
            raise ValidationError({'refresh': 'Token inválido ou já expirado.'})
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(generics.RetrieveUpdateAPIView):
    """GET /api/auth/me/ — perfil | PATCH — atualizar preferências."""
    http_method_names = ['get', 'patch']

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method == 'PATCH':
            return UserFormSerializer
        return UserDetailSerializer


class ForgotPasswordView(APIView):
    """POST /api/auth/password/forgot/ — envia código de recuperação por e-mail."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        if email:
            try:
                user = User.objects.get(email__iexact=email)
                code = PasswordResetCode.generate(user)
                nome = user.get_full_name() or user.username
                send_mail(
                    subject='Seu código de recuperação — Rachei',
                    message=(
                        f'Olá, {nome}!\n\n'
                        f'Seu código de recuperação de senha é:\n\n'
                        f'  {code}\n\n'
                        f'Ele é válido por {PasswordResetCode.CODE_TTL_MINUTES} minutos '
                        f'e pode ser usado apenas uma vez.\n\n'
                        f'Se você não solicitou isso, ignore este e-mail com segurança.'
                    ),
                    from_email=django_settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=True,
                )
            except User.DoesNotExist:
                pass  # resposta neutra — não revelamos se o e-mail existe
        return Response({'detail': _NEUTRAL_FORGOT})


class ResetPasswordView(APIView):
    """POST /api/auth/password/reset/ — valida código e redefine a senha."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        code = (request.data.get('code') or '').strip()
        new_password = request.data.get('password') or ''

        errors = {}
        if not email:
            errors['email'] = ['Campo obrigatório.']
        if not code:
            errors['code'] = ['Campo obrigatório.']
        if not new_password:
            errors['password'] = ['Campo obrigatório.']
        if errors:
            raise ValidationError(errors)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise ValidationError(_INVALID_CODE)

        # Valida força da senha antes de consumir o código (fail-fast)
        try:
            validate_password(new_password, user)
        except DjangoValidationError as exc:
            raise ValidationError({'password': list(exc.messages)})

        reset_code = (
            PasswordResetCode.objects
            .filter(user=user)
            .order_by('-created_at')
            .first()
        )

        if not reset_code or not reset_code.is_valid():
            raise ValidationError(_INVALID_CODE)

        if not reset_code.verify_and_consume(code):
            raise ValidationError(_INVALID_CODE)

        # Altera a senha
        user.set_password(new_password)
        user.save(update_fields=['password'])

        # Invalida todos os refresh tokens ativos (logout em todos os dispositivos)
        outstanding = OutstandingToken.objects.filter(user=user)
        BlacklistedToken.objects.bulk_create(
            [BlacklistedToken(token=t) for t in outstanding],
            ignore_conflicts=True,
        )

        # E-mail de confirmação (best-effort)
        nome = user.get_full_name() or user.username
        send_mail(
            subject='Senha alterada — Rachei',
            message=(
                f'Olá, {nome}!\n\n'
                f'Sua senha foi redefinida com sucesso. '
                f'Todos os seus dispositivos foram desconectados.\n\n'
                f'Se não foi você, entre em contato imediatamente.'
            ),
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )

        return Response({'detail': 'Senha redefinida com sucesso.'})


# ---------------------------------------------------------------------------
# 2FA — Configuração
# ---------------------------------------------------------------------------

class TwoFactorSetupView(APIView):
    """GET /api/auth/2fa/setup/ — retorna secret + URI para o QR code."""

    def get(self, request):
        config = TwoFactorConfig.objects.filter(user=request.user, is_active=True).first()
        if config:
            return Response({'detail': 'Autenticador já ativo.'}, status=status.HTTP_400_BAD_REQUEST)

        config, created = TwoFactorConfig.objects.get_or_create(user=request.user)
        if created or not config.secret:
            config.secret = pyotp.random_base32()
            config.is_active = False
            config.save(update_fields=['secret', 'is_active'])

        otpauth_uri = pyotp.TOTP(config.secret).provisioning_uri(
            name=request.user.email,
            issuer_name='Rachei',
        )
        return Response({'secret': config.secret, 'otpauth_uri': otpauth_uri})


class TwoFactorSetupConfirmView(APIView):
    """POST /api/auth/2fa/setup/confirm/ — verifica TOTP e ativa 2FA."""

    def post(self, request):
        code = (request.data.get('code') or '').strip().replace(' ', '')
        if not code:
            raise ValidationError({'code': ['Campo obrigatório.']})

        try:
            config = TwoFactorConfig.objects.get(user=request.user, is_active=False)
        except TwoFactorConfig.DoesNotExist:
            raise ValidationError({'detail': 'Configuração não encontrada. Inicie o setup novamente.'})

        if not pyotp.TOTP(config.secret).verify(code, valid_window=1):
            raise ValidationError({'code': ['Código inválido.']})

        codes = generate_backup_codes(8)
        config.is_active = True
        config.backup_codes = [hashlib.sha256(c.encode()).hexdigest() for c in codes]
        config.save(update_fields=['is_active', 'backup_codes', 'updated_at'])

        return Response({'backup_codes': codes})


class TwoFactorRegenerateBackupCodesView(APIView):
    """POST /api/auth/2fa/backup-codes/regenerate/ — recria backup codes (requer TOTP válido)."""

    def post(self, request):
        code = (request.data.get('code') or '').strip().replace(' ', '')
        if not code:
            raise ValidationError({'code': ['Campo obrigatório.']})

        try:
            config = TwoFactorConfig.objects.get(user=request.user, is_active=True)
        except TwoFactorConfig.DoesNotExist:
            raise ValidationError({'detail': 'Autenticador não está ativo.'})

        if not pyotp.TOTP(config.secret).verify(code, valid_window=1):
            raise ValidationError({'code': ['Código inválido.']})

        codes = generate_backup_codes(8)
        config.backup_codes = [hashlib.sha256(c.encode()).hexdigest() for c in codes]
        config.save(update_fields=['backup_codes', 'updated_at'])

        return Response({'backup_codes': codes})


# ---------------------------------------------------------------------------
# 2FA — Challenge (durante o login)
# ---------------------------------------------------------------------------

class TwoFactorChallengeView(APIView):
    """POST /api/auth/2fa/challenge/ — verifica TOTP no fluxo de login."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        pending_str = (request.data.get('pending_token') or '').strip()
        code = (request.data.get('code') or '').strip()
        trust_device = bool(request.data.get('trust_device', False))

        if not pending_str or not code:
            raise ValidationError({'detail': 'pending_token e code são obrigatórios.'})

        try:
            token = TwoFAPendingToken(pending_str)
            user_id = token['user_id']
        except (TokenError, KeyError):
            raise ValidationError({'detail': 'Token inválido ou expirado.'})

        user = User.objects.filter(pk=user_id).first()
        if not user:
            raise ValidationError({'detail': 'Token inválido ou expirado.'})

        config = TwoFactorConfig.objects.filter(user=user, is_active=True).first()
        if not config:
            raise ValidationError({'detail': 'Token inválido ou expirado.'})

        if not config.verify_totp_or_backup(code):
            raise ValidationError({'code': ['Código inválido.']})

        refresh = RefreshToken.for_user(user)
        refresh['plan'] = user.plan

        data = {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserDetailSerializer(user).data,
        }

        if trust_device:
            td_token = secrets.token_hex(32)
            TrustedDevice.objects.create(
                user=user,
                token_hash=hashlib.sha256(td_token.encode()).hexdigest(),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:256],
                expires_at=timezone.now() + timedelta(days=30),
            )
            data['trusted_device_token'] = td_token

        return Response(data)


# ---------------------------------------------------------------------------
# 2FA — Desativação
# ---------------------------------------------------------------------------

class TwoFactorDisableView(APIView):
    """POST /api/auth/2fa/disable/ — desativa 2FA (requer senha + TOTP)."""
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        password = request.data.get('password') or ''
        code = (request.data.get('code') or '').strip()

        if not password or not code:
            raise ValidationError({'detail': 'password e code são obrigatórios.'})

        if not request.user.check_password(password):
            raise ValidationError({'password': ['Senha incorreta.']})

        try:
            config = TwoFactorConfig.objects.get(user=request.user, is_active=True)
        except TwoFactorConfig.DoesNotExist:
            raise ValidationError({'detail': 'Autenticador não está ativo.'})

        if not config.verify_totp_or_backup(code):
            raise ValidationError({'code': ['Código inválido.']})

        config.is_active = False
        config.secret = ''
        config.backup_codes = []
        config.save(update_fields=['is_active', 'secret', 'backup_codes', 'updated_at'])

        TrustedDevice.objects.filter(user=request.user).delete()

        return Response({'detail': 'Autenticador desativado com sucesso.'})


class TwoFactorStatusView(APIView):
    """GET /api/auth/2fa/status/ — retorna se o 2FA está ativo para o usuário."""

    def get(self, request):
        config = TwoFactorConfig.objects.filter(user=request.user).first()
        return Response({'is_active': bool(config and config.is_active)})
