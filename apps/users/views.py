from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView as BaseTokenObtainPairView

from .models import PasswordResetCode
from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserDetailSerializer,
    UserFormSerializer,
)
from .throttles import AuthRateThrottle

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
