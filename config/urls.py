from django.conf import settings
from django.contrib import admin
from django.urls import path, include

from apps.users.views import CustomTokenObtainPairView, CookieTokenRefreshView
from config.observability import health_view

urlpatterns = [
    path('health/', health_view, name='health'),
    path(settings.ADMIN_URL, admin.site.urls),
    # Auth
    path('api/auth/login/', CustomTokenObtainPairView.as_view(), name='token_login'),
    path('api/auth/refresh/', CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/', include('apps.users.urls')),
    # Apps
    path('api/', include('apps.groups.urls')),
    path('api/', include('apps.debts.urls')),
    path('api/', include('apps.payments.urls')),
]

# Rotas de suporte a E2E — SOMENTE sob settings_e2e (E2E_MODE). Nunca em produção.
if getattr(settings, 'E2E_MODE', False):
    urlpatterns += [path('api/', include('apps.e2e.urls'))]

# Rota de teste de observabilidade — SOMENTE em DEBUG (nunca em produção).
# Levanta uma exceção real: exercita Sentry (stack trace) + Better Stack
# (log ERROR de django.request com request_id).
if settings.DEBUG:
    def _trigger_error(request):
        raise RuntimeError('Erro de teste do Rachei (observabilidade)')

    urlpatterns += [path('sentry-debug/', _trigger_error)]
