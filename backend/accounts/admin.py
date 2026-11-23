from django.contrib import admin
from .models import SiteOptions

@admin.register(SiteOptions)
class SiteOptionsAdmin(admin.ModelAdmin):
    list_display = ("registration_open", "updated_at")
    def has_add_permission(self, request):
        return super().has_add_permission(request) and not SiteOptions.objects.exists()
    def has_delete_permission(self, request, obj=None):
        return False
