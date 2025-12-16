from django.contrib import admin
from .models import Contact, Newsletter


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "full_name",
        "email",
        "subject",
        "is_seen",
        "created_date",
    )
    list_filter = ("is_seen", "created_date")
    search_fields = ("full_name", "email", "subject")
    ordering = ("-created_date",)


@admin.register(Newsletter)
class NewsletterAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "created_date")
    search_fields = ("email",)
