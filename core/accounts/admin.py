# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session

from .models import Profile

User = get_user_model()


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    list_display = ("id", "email", "is_superuser", "is_active", "is_verified")
    list_filter = ("is_superuser", "is_active", "is_verified")
    search_fields = ("email",)
    ordering = ("email",)

    fieldsets = (
        ("Authentication", {"fields": ("email", "password")}),
        ("Permissions", {
            "fields": (
                "is_staff",
                "is_active",
                "is_superuser",
                "is_verified",
                "type",
                "groups",
                "user_permissions",
            )
        }),
        ("Important dates", {"fields": ("last_login",)}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                    "is_superuser",
                    "is_verified",
                    "type",
                ),
            },
        ),
    )


@admin.register(Profile)
class CustomProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "first_name", "last_name", "phone_number")
    search_fields = ("user__email", "first_name", "last_name", "phone_number")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("session_key", "expire_date")
    readonly_fields = ("session_key", "expire_date")
