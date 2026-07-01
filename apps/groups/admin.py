from django.contrib import admin
from .models import Group, GroupMember


class GroupMemberInline(admin.TabularInline):
    model = GroupMember
    extra = 0


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'emoji', 'created_by', 'created_at')
    inlines = [GroupMemberInline]
