from django.contrib import admin
from .models import PaymentModel

@admin.register(PaymentModel)
class PaymentAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "order",
        "gateway",
        "authority_id",
        "ref_id",
        "amount",
        "status",
        "is_consumed",
        "paid_date",
        "created_date",
        "is_refunded",
        "is_verified",
    )

    list_filter = (
        "status",
        "gateway",
        "is_consumed",
        "created_date",
    )

    search_fields = (
        "authority_id",
        "ref_id",
        "order__id",
        "order__user__username",
        "order__user__email",
    )

    autocomplete_fields = (
        "order",
        "refunded_by",
    )

    readonly_fields = (
        "authority_id",
        "ref_id",
        "amount",
        "gateway",
        "request_payload",
        "response_payload",
        "refund_request",
        "refund_response",
        "paid_date",
        "verified_date",
        "refund_date",
        "created_date",
        "updated_date",
    )

    ordering = (
        "-created_date",
    )