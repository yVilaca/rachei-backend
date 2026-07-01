from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'plan', 'is_staff')
    list_filter = ('plan', 'is_staff', 'is_active')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Rachei', {'fields': ('plan',)}),
    )
