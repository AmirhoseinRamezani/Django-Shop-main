import json
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from payment.models import (
    GatewayLog,
    PaymentAttempt,
    PaymentModel,
    Refund,
)


# ==============================================================================
# INLINES
# ==============================================================================

class GatewayLogInline(admin.TabularInline):
    """
    نمایش لاگ‌های درگاه به‌صورت Read-Only در صفحات PaymentAttempt و Refund
    """
    model = GatewayLog
    extra = 0
    can_delete = False
    fields = (
        "created_date",
        "gateway",
        "log_type",
        "direction",
        "http_status",
        "latency_badge",
        "is_success_badge",
    )
    readonly_fields = (
        "created_date",
        "gateway",
        "log_type",
        "direction",
        "http_status",
        "latency_badge",
        "is_success_badge",
    )
    show_change_link = True
    ordering = ("-created_date",)

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Latency"))
    def latency_badge(self, obj):
        if obj.latency_ms is None:
            return "-"
        color = "green" if obj.latency_ms < 1000 else ("orange" if obj.latency_ms < 3000 else "red")
        return format_html('<span style="color: {}; font-weight: bold;">{} ms</span>', color, obj.latency_ms)

    @admin.display(description=_("Success"))
    def is_success_badge(self, obj):
        if obj.is_success is None:
            return format_html('<span style="color: gray;">-</span>')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            "green" if obj.is_success else "red",
            "✔ Success" if obj.is_success else "✘ Failed",
        )


class PaymentAttemptInline(admin.StackedInline):
    """
    نمایش تمامی تلاش‌های پرداخت در صفحه اصلی PaymentModel
    """
    model = PaymentAttempt
    extra = 0
    can_delete = False
    show_change_link = True
    ordering = ("-attempt_number",)
    
    fields = (
        ("attempt_number", "status", "retry_count"),
        ("authority_id", "gateway_reference", "gateway_transaction_id"),
        ("response_code", "gateway_message", "failure_reason"),
        ("started_at", "finished_at", "latency_ms"),
    )
    
    # تاپل تک‌بعدی مسطح بدون گروه بندی تکراری
    readonly_fields = (
        "attempt_number",
        "status",
        "retry_count",
        "authority_id",
        "gateway_reference",
        "gateway_transaction_id",
        "response_code",
        "gateway_message",
        "failure_reason",
        "started_at",
        "finished_at",
        "latency_ms",
    )

    def has_add_permission(self, request, obj=None):
        return False


class RefundInline(admin.TabularInline):
    """
    نمایش استردادهای مرتبط در صفحه اصلی PaymentModel
    """
    model = Refund
    extra = 0
    can_delete = False
    show_change_link = True
    fields = (
        "idempotency_key",
        "amount",
        "currency",
        "status",
        "reason",
        "requested_at",
    )
    readonly_fields = (
        "idempotency_key",
        "amount",
        "currency",
        "status",
        "reason",
        "requested_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


# ==============================================================================
# ADMIN CLASSES
# ==============================================================================

@admin.register(PaymentModel)
class PaymentModelAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "amount_formatted",
        "gateway",
        "status_badge",
        "is_consumed",
        "is_refunded",
        "created_date",
    )
    list_filter = ("status", "gateway", "is_consumed", "is_refunded", "currency", "created_date")
    search_fields = ("id", "order__id", "order__user__email")
    readonly_fields = ("version", "created_date", "updated_date")
    raw_id_fields = ("order",)
    inlines = [PaymentAttemptInline, RefundInline]
    date_hierarchy = "created_date"
    ordering = ("-created_date",)

    @admin.display(description=_("Amount"))
    def amount_formatted(self, obj):
        return f"{obj.amount:,.0f} {obj.currency}"

    @admin.display(description=_("Status"))
    def status_badge(self, obj):
        return format_html(
            '<span style="font-weight: bold;">{}</span>',
            obj.get_status_display() if hasattr(obj, "get_status_display") else obj.status,
        )


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "payment_link",
        "attempt_number",
        "status_badge",
        "authority_id",
        "gateway_reference",
        "started_at",
        "latency_ms",
    )
    list_filter = ("status", "started_at")
    search_fields = (
        "authority_id",
        "gateway_reference",
        "gateway_transaction_id",
        "payment__id",
    )
    readonly_fields = (
        "payment",
        "retry_of",
        "attempt_number",
        "retry_count",
        "started_at",
        "finished_at",
        "latency_ms",
        "ip_address",
        "user_agent",
        "pretty_meta",
    )
    inlines = [GatewayLogInline]
    date_hierarchy = "started_at"
    ordering = ("-started_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("payment")

    def has_add_permission(self, request):
        return False

    @admin.display(description=_("Payment"))
    def payment_link(self, obj):
        return format_html('<a href="/admin/payment/paymentmodel/{}/change/">#{}</a>', obj.payment_id, obj.payment_id)

    @admin.display(description=_("Status"))
    def status_badge(self, obj):
        return format_html('<b>{}</b>', obj.get_status_display() if hasattr(obj, "get_status_display") else obj.status)

    @admin.display(description=_("Metadata"))
    def pretty_meta(self, obj):
        return format_html("<pre>{}</pre>", json.dumps(obj.meta, indent=2, ensure_ascii=False))


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "payment_link",
        "amount_formatted",
        "reason",
        "status_badge",
        "gateway_reference",
        "requested_at",
    )
    list_filter = ("status", "reason", "currency", "requested_at")
    search_fields = (
        "idempotency_key",
        "gateway_reference",
        "gateway_transaction_id",
        "payment__id",
    )
    readonly_fields = (
        "payment",
        "amount",
        "currency",
        "idempotency_key",
        "reason",
        "reason_detail",
        "requested_at",
        "finished_at",
        "latency_ms",
        "ip_address",
        "user_agent",
        "pretty_meta",
    )
    inlines = [GatewayLogInline]
    date_hierarchy = "requested_at"
    ordering = ("-requested_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("payment")

    def has_add_permission(self, request):
        return False

    @admin.display(description=_("Payment"))
    def payment_link(self, obj):
        return format_html('<a href="/admin/payment/paymentmodel/{}/change/">#{}</a>', obj.payment_id, obj.payment_id)

    @admin.display(description=_("Amount"))
    def amount_formatted(self, obj):
        return f"{obj.amount:,.0f} {obj.currency}"

    @admin.display(description=_("Status"))
    def status_badge(self, obj):
        return format_html('<b>{}</b>', obj.get_status_display() if hasattr(obj, "get_status_display") else obj.status)

    @admin.display(description=_("Metadata"))
    def pretty_meta(self, obj):
        return format_html("<pre>{}</pre>", json.dumps(obj.meta, indent=2, ensure_ascii=False))


@admin.register(GatewayLog)
class GatewayLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_date",
        "gateway",
        "log_type",
        "direction",
        "http_status_badge",
        "is_success_badge",
        "latency_ms",
        "owner_link",
    )
    list_filter = ("gateway", "log_type", "direction", "is_success", "created_date")
    search_fields = (
        "request_url",
        "response_code",
        "gateway_message",
        "attempt__authority_id",
        "refund__idempotency_key",
    )
    date_hierarchy = "created_date"
    ordering = ("-created_date",)

    readonly_fields = [f.name for f in GatewayLog._meta.fields] + [
        "pretty_request_headers",
        "pretty_request_payload",
        "pretty_response_headers",
        "pretty_response_payload",
        "pretty_meta",
    ]

    fieldsets = (
        (_("Ownership & Context"), {
            "fields": ("attempt", "refund", "gateway", "log_type", "direction", "created_date")
        }),
        (_("HTTP & Transport"), {
            "fields": ("request_url", "request_method", "http_status", "latency_ms")
        }),
        (_("Normalized Result"), {
            "fields": ("is_success", "response_code", "gateway_message", "exception")
        }),
        (_("Raw Payloads (Forensic Evidence)"), {
            "classes": ("collapse",),
            "fields": (
                "pretty_request_headers",
                "pretty_request_payload",
                "pretty_response_headers",
                "pretty_response_payload",
            )
        }),
        (_("Client Metadata"), {
            "classes": ("collapse",),
            "fields": ("ip_address", "user_agent", "pretty_meta")
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("attempt", "refund")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Owner"))
    def owner_link(self, obj):
        if obj.attempt_id:
            return format_html('<a href="/admin/payment/paymentattempt/{}/change/">Attempt #{}</a>', obj.attempt_id, obj.attempt_id)
        if obj.refund_id:
            return format_html('<a href="/admin/payment/refund/{}/change/">Refund #{}</a>', obj.refund_id, obj.refund_id)
        return "-"

    @admin.display(description=_("HTTP Status"))
    def http_status_badge(self, obj):
        if not obj.http_status:
            return "-"
        color = "green" if 200 <= obj.http_status < 300 else "red"
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.http_status)

    @admin.display(description=_("Success"))
    def is_success_badge(self, obj):
        if obj.is_success is None:
            return "-"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            "green" if obj.is_success else "red",
            "✔ Success" if obj.is_success else "✘ Failed",
        )

    def _format_json(self, data):
        return format_html("<pre>{}</pre>", json.dumps(data or {}, indent=2, ensure_ascii=False))

    @admin.display(description=_("Request Headers"))
    def pretty_request_headers(self, obj):
        return self._format_json(obj.request_headers)

    @admin.display(description=_("Request Payload"))
    def pretty_request_payload(self, obj):
        return self._format_json(obj.request_payload)

    @admin.display(description=_("Response Headers"))
    def pretty_response_headers(self, obj):
        return self._format_json(obj.response_headers)

    @admin.display(description=_("Response Payload"))
    def pretty_response_payload(self, obj):
        return self._format_json(obj.response_payload)

    @admin.display(description=_("Metadata"))
    def pretty_meta(self, obj):
        return self._format_json(obj.meta)