
from django.contrib import admin

from events.models.outbox import OutboxEvent


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event_id",
        "topic",
        "status",
        "retry_count",
        "created_date",
        "processed_date",
        "available_at",
        "claimed_at",
    )
    list_filter = ("status", "topic")
    search_fields = ("event_id", "topic")
    readonly_fields = (
        "event_id",
        "topic",
        "payload",
        "status",
        "retry_count",
        "last_error",
        "created_date",
        "processed_date",
        "available_at",
        "claimed_at",
        "claim_token",
    )
    ordering = ("-created_date",)
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False