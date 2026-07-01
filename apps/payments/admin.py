from django.contrib import admin
from .models import ChargeLink


@admin.register(ChargeLink)
class ChargeLinkAdmin(admin.ModelAdmin):
    list_display = ('installment', 'token', 'expires_at', 'is_expired', 'created_at')
    readonly_fields = ('token', 'created_at')
