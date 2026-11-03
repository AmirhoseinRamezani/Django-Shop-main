from django.contrib import admin
from events.models.outbox import OutboxEvent


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "topic",
        "status",
        "retry_count",
        "created_date",
        "processed_date",
        "available_at",
        "claimed_at",
    )
    list_filter = ("status", "topic")
    search_fields = ("topic", "payload")
    readonly_fields = (
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
