from django.urls import path

from .views import (
    ForgotPasswordView,
    LogoutView,
    MeView,
    RegisterView,
    ResendSmsView,
    ResetPasswordView,
    TrustedDeviceDeleteView,
    TrustedDeviceListView,
    TwoFactorChallengeView,
    TwoFactorDisableView,
    TwoFactorRegenerateBackupCodesView,
    TwoFactorSetupConfirmView,
    TwoFactorSetupView,
    TwoFactorStatusView,
    VerifyPhoneView,
)

app_name = 'users'

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('phone/verify/', VerifyPhoneView.as_view(), name='phone_verify'),
    path('phone/resend/', ResendSmsView.as_view(), name='phone_resend'),
    path('me/', MeView.as_view(), name='me'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('password/forgot/', ForgotPasswordView.as_view(), name='password_forgot'),
    path('password/reset/', ResetPasswordView.as_view(), name='password_reset'),
    # 2FA
    path('2fa/status/', TwoFactorStatusView.as_view(), name='2fa_status'),
    path('2fa/setup/', TwoFactorSetupView.as_view(), name='2fa_setup'),
    path('2fa/setup/confirm/', TwoFactorSetupConfirmView.as_view(), name='2fa_setup_confirm'),
    path('2fa/challenge/', TwoFactorChallengeView.as_view(), name='2fa_challenge'),
    path('2fa/disable/', TwoFactorDisableView.as_view(), name='2fa_disable'),
    path('2fa/backup-codes/regenerate/', TwoFactorRegenerateBackupCodesView.as_view(), name='2fa_backup_codes_regenerate'),
    path('2fa/trusted-devices/', TrustedDeviceListView.as_view(), name='2fa_trusted_devices'),
    path('2fa/trusted-devices/<int:pk>/', TrustedDeviceDeleteView.as_view(), name='2fa_trusted_device_delete'),
]
