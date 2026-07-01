from django.contrib import admin
from .models import Debt, Installment


class InstallmentInline(admin.TabularInline):
    model = Installment
    extra = 0
    readonly_fields = ('paid_at', 'confirmed_at')


@admin.register(Debt)
class DebtAdmin(admin.ModelAdmin):
    list_display = ('description', 'group', 'paid_by', 'total_amount_cents', 'split_type', 'created_at')
    list_filter = ('split_type',)
    inlines = [InstallmentInline]


@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = ('debt', 'debtor', 'amount_cents', 'status', 'paid_at', 'confirmed_at')
    list_filter = ('status',)
