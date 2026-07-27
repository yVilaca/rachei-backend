import hashlib
import logging
import re
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
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView as BaseTokenObtainPairView

from .models import AuditLog, PasswordResetCode, SmsVerification, TrustedDevice, TwoFactorConfig, TOTPLocked, generate_backup_codes
from .audit import log_event
from apps.groups.whatsapp import send_whatsapp
from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserDetailSerializer,
    UserFormSerializer,
)
from .throttles import AuthRateThrottle, LoginRateThrottle, PasswordResetRateThrottle, PhoneCheckRateThrottle
from .tokens import TwoFAPendingToken

logger = logging.getLogger('apps.users')

# ---------------------------------------------------------------------------
# Cookie helpers — refresh token HttpOnly
# ---------------------------------------------------------------------------

REFRESH_COOKIE_NAME = 'rachei_refresh'
_REFRESH_MAX_AGE = int(django_settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds())


def _set_refresh_cookie(response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=_REFRESH_MAX_AGE,
        httponly=True,
        secure=not django_settings.DEBUG,
        samesite='Strict',
        path='/api/auth/',
    )


def _clear_refresh_cookie(response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path='/api/auth/')


def _log(request, event: str, user=None, detail: dict | None = None) -> None:
    """Auditoria de eventos de auth — delega ao helper compartilhado."""
    log_event(request, event, user=user, detail=detail)


def _send_verification_code(user) -> None:
    try:
        code = SmsVerification.generate(user)
        send_whatsapp(
            user.phone,
            f'Rachei: seu código de verificação é {code}. Válido por {SmsVerification.CODE_TTL_MINUTES} minutos.',
        )
    except Exception:
        # Fronteira fire-and-forget: nunca bloqueia o cadastro, mas registra o
        # motivo (backend pode ser qualquer um; log > silêncio para diagnóstico).
        logger.exception('verificacao_codigo_falhou user=%s', user.pk)


def _link_pending_contacts(user) -> list:
    """Ao verificar o telefone, migra ContatoPendente → GroupMember(pendente_confirmacao)."""
    from apps.groups.models import ContatoPendente, GroupMember
    contatos = list(
        ContatoPendente.objects
        .filter(phone=user.phone)
        .prefetch_related('group_memberships__group')
    )
    pending_groups = []
    for contato in contatos:
        for membership in contato.group_memberships.all():
            membership.user = user
            membership.contato_pendente = None
            membership.status = GroupMember.STATUS_PENDENTE_CONFIRMACAO
            membership.save(update_fields=['user', 'contato_pendente', 'status'])
            pending_groups.append({
                'id': str(membership.group.id),
                'name': membership.group.name,
                'emoji': membership.group.emoji,
            })
        contato.delete()
    return pending_groups


_NEUTRAL_FORGOT = 'Se esse e-mail estiver cadastrado, você receberá um código em breve.'
_INVALID_CODE = {'code': ['Código inválido ou expirado.']}

User = get_user_model()


class CustomTokenObtainPairView(BaseTokenObtainPairView):
    """POST /api/auth/login/ — autentica e retorna tokens + dados do usuário."""
    throttle_classes = [LoginRateThrottle]
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
        except Exception:
            _log(request, AuditLog.LOGIN_FAIL,
                 detail={'email': str(request.data.get('email', ''))[:100]})
            raise
        if 'refresh' in response.data:
            # Login completo — sem 2FA ou trusted device aceito
            _set_refresh_cookie(response, response.data.pop('refresh'))
            _log(request, AuditLog.LOGIN_OK)
        # 2FA pendente: não loga LOGIN_OK — TOTP_OK será registrado após o challenge
        return response


class RegisterView(generics.CreateAPIView):
    """POST /api/auth/register/ — cria conta, envia OTP SMS e retorna tokens JWT."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthRateThrottle]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        _send_verification_code(user)
        refresh = RefreshToken.for_user(user)
        refresh['plan'] = user.plan
        response = Response({
            'access': str(refresh.access_token),
            'user': UserDetailSerializer(user).data,
            'phone_verification_required': True,
        }, status=status.HTTP_201_CREATED)
        _set_refresh_cookie(response, str(refresh))
        return response


class VerifyPhoneView(APIView):
    """POST /api/auth/phone/verify/ — verifica OTP enviado por SMS."""
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        code = (request.data.get('code') or '').strip()
        if not code:
            raise ValidationError({'code': ['Campo obrigatório.']})

        verification = SmsVerification.objects.filter(user=request.user).first()
        if not verification or not verification.is_valid():
            raise ValidationError({'detail': 'Código inválido ou expirado.'})

        if not verification.verify_and_consume(code):
            raise ValidationError({'code': ['Código inválido.']})

        request.user.phone_verified = True
        request.user.save(update_fields=['phone_verified'])

        pending_groups = _link_pending_contacts(request.user)

        return Response({
            'detail': 'Telefone verificado com sucesso.',
            'pending_groups': pending_groups,
        })


class ResendSmsView(APIView):
    """POST /api/auth/phone/resend/ — reenvia OTP SMS."""
    throttle_classes = [PasswordResetRateThrottle]

    def post(self, request):
        if request.user.phone_verified:
            return Response({'detail': 'Telefone já verificado.'}, status=status.HTTP_400_BAD_REQUEST)
        _send_verification_code(request.user)
        return Response({'detail': 'Código reenviado.'})


class LogoutView(APIView):
    """POST /api/auth/logout/ — invalida o refresh token do cookie e o limpa."""

    def post(self, request):
        refresh_str = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if refresh_str:
            try:
                token = RefreshToken(refresh_str)
                token.blacklist()
            except TokenError:
                pass  # token já expirado — seguro ignorar; cookie será limpo
        response = Response(status=status.HTTP_205_RESET_CONTENT)
        _clear_refresh_cookie(response)
        return response


class CookieTokenRefreshView(APIView):
    """POST /api/auth/refresh/ — renova access token usando o cookie HttpOnly."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        refresh_str = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if not refresh_str:
            return Response({'detail': 'Sessão expirada.'}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = TokenRefreshSerializer(data={'refresh': refresh_str})
        try:
            serializer.is_valid(raise_exception=True)
        except (TokenError, InvalidToken):
            response = Response({'detail': 'Sessão expirada.'}, status=status.HTTP_401_UNAUTHORIZED)
            _clear_refresh_cookie(response)
            return response

        data = serializer.validated_data
        response = Response({'access': data['access']})
        if 'refresh' in data:
            _set_refresh_cookie(response, data['refresh'])
        _log(request, AuditLog.TOKEN_REFRESH)
        return response


class MeView(generics.RetrieveUpdateAPIView):
    """GET /api/auth/me/ — perfil | PATCH — atualizar preferências."""
    http_method_names = ['get', 'patch']

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method == 'PATCH':
            return UserFormSerializer
        return UserDetailSerializer

    def update(self, request, *args, **kwargs):
        # Valida/salva com o UserFormSerializer e devolve o perfil completo.
        super().update(request, *args, **kwargs)
        return Response(UserDetailSerializer(self.get_object()).data)


class ForgotPasswordView(APIView):
    """POST /api/auth/password/forgot/ — envia código de recuperação por e-mail."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PasswordResetRateThrottle]

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
    throttle_classes = [PasswordResetRateThrottle]

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

        # Invalida todos os refresh tokens ativos + revoga dispositivos confiados
        outstanding = OutstandingToken.objects.filter(user=user)
        BlacklistedToken.objects.bulk_create(
            [BlacklistedToken(token=t) for t in outstanding],
            ignore_conflicts=True,
        )
        TrustedDevice.objects.filter(user=user).delete()
        _log(request, AuditLog.PWD_RESET, user=user)

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

        # Força re-autenticação em todos os dispositivos após ativar 2FA
        outstanding = OutstandingToken.objects.filter(user=request.user)
        BlacklistedToken.objects.bulk_create(
            [BlacklistedToken(token=t) for t in outstanding],
            ignore_conflicts=True,
        )
        _log(request, AuditLog.TWO_FA_ON, user=request.user)

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

        try:
            verified = config.verify_totp_or_backup(code)
        except TOTPLocked:
            _log(request, AuditLog.TOTP_LOCKED, user=request.user)
            raise ValidationError({'detail': 'Muitas tentativas incorretas. Aguarde alguns minutos e tente novamente.'})

        if not verified:
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

        try:
            verified = config.verify_totp_or_backup(code)
        except TOTPLocked:
            _log(request, AuditLog.TOTP_LOCKED, user=user)
            raise ValidationError({'detail': 'Muitas tentativas incorretas. Aguarde alguns minutos e tente novamente.'})

        if not verified:
            _log(request, AuditLog.TOTP_FAIL, user=user)
            raise ValidationError({'code': ['Código inválido.']})

        refresh = RefreshToken.for_user(user)
        refresh['plan'] = user.plan

        response_data = {
            'access': str(refresh.access_token),
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
            response_data['trusted_device_token'] = td_token

        response = Response(response_data)
        _set_refresh_cookie(response, str(refresh))
        _log(request, AuditLog.TOTP_OK, user=user)
        return response


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

        try:
            verified = config.verify_totp_or_backup(code)
        except TOTPLocked:
            _log(request, AuditLog.TOTP_LOCKED, user=request.user)
            raise ValidationError({'detail': 'Muitas tentativas incorretas. Aguarde alguns minutos e tente novamente.'})

        if not verified:
            raise ValidationError({'code': ['Código inválido.']})

        config.is_active = False
        config.secret = ''
        config.backup_codes = []
        config.save(update_fields=['is_active', 'secret', 'backup_codes', 'updated_at'])

        TrustedDevice.objects.filter(user=request.user).delete()

        # Invalida todos os refresh tokens ao desativar 2FA
        outstanding = OutstandingToken.objects.filter(user=request.user)
        BlacklistedToken.objects.bulk_create(
            [BlacklistedToken(token=t) for t in outstanding],
            ignore_conflicts=True,
        )
        _log(request, AuditLog.TWO_FA_OFF, user=request.user)

        return Response({'detail': 'Autenticador desativado com sucesso.'})


class TwoFactorStatusView(APIView):
    """GET /api/auth/2fa/status/ — retorna se o 2FA está ativo para o usuário."""

    def get(self, request):
        config = TwoFactorConfig.objects.filter(user=request.user).first()
        backup_remaining = len(config.backup_codes) if config and config.is_active else 0
        return Response({
            'is_active': bool(config and config.is_active),
            'backup_codes_remaining': backup_remaining,
        })


class TrustedDeviceListView(APIView):
    """GET /api/auth/2fa/trusted-devices/ — lista dispositivos confiados (não expirados)."""

    def get(self, request):
        devices = TrustedDevice.objects.filter(
            user=request.user,
            expires_at__gt=timezone.now(),
        ).order_by('-created_at')
        return Response([{
            'id': d.id,
            'user_agent': d.user_agent or 'Desconhecido',
            'created_at': d.created_at,
            'last_used_at': d.last_used_at,
            'expires_at': d.expires_at,
        } for d in devices])


class TrustedDeviceDeleteView(APIView):
    """DELETE /api/auth/2fa/trusted-devices/<pk>/ — revoga um dispositivo específico."""

    def delete(self, request, pk):
        deleted, _ = TrustedDevice.objects.filter(pk=pk, user=request.user).delete()
        if not deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


_E164_RE = re.compile(r'^\+\d{8,15}$')

User = get_user_model()


class CheckPhoneExistsView(APIView):
    """GET /api/auth/check-phone/?phone=+55... — verifica se telefone tem conta cadastrada.

    Retorna apenas {"exists": bool}. Nunca expõe dados do usuário.
    Requer autenticação para prevenir enumeração pública.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [PhoneCheckRateThrottle]

    def get(self, request):
        phone = request.query_params.get('phone', '').strip()
        if not _E164_RE.match(phone):
            return Response({'exists': False})
        exists = User.objects.filter(phone=phone).exists()
        return Response({'exists': exists})
