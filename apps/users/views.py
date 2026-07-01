from django.contrib.auth import get_user_model
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView as BaseTokenObtainPairView

from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserDetailSerializer,
    UserFormSerializer,
)
from .throttles import AuthRateThrottle

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
