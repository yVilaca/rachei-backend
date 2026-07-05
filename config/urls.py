from django.conf import settings
from django.contrib import admin
from django.urls import path, include

from apps.users.views import CustomTokenObtainPairView, CookieTokenRefreshView

urlpatterns = [
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
