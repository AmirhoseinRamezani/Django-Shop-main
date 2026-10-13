# core/payment/admin.py
import logging

from django import forms
from django.contrib.admin.helpers import ActionForm

from django.contrib import admin

from payment.models import (
    PaymentAttempt,
    PaymentModel,
    PaymentResolution,
    PaymentResolutionStatus,
    Refund,
)
from payment.services.payment_resolution import PaymentResolutionService

logger = logging.getLogger(__name__)


class PaymentResolutionActionForm(ActionForm):
    resolution_note = forms.CharField(
        label="Resolution note",
        required=True,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3, "cols": 80}),
        help_text="Record the evidence reviewed and the operational action taken.",
    )


class _FinancialReadOnlyAdmin(admin.ModelAdmin):
    """Prevent Django Admin from becoming a second financial write path."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PaymentModelAdmin(_FinancialReadOnlyAdmin):
    readonly_fields = tuple(field.name for field in PaymentModel._meta.fields)


class PaymentAttemptAdmin(_FinancialReadOnlyAdmin):
    readonly_fields = tuple(field.name for field in PaymentAttempt._meta.fields)


class RefundAdmin(_FinancialReadOnlyAdmin):
    readonly_fields = tuple(field.name for field in Refund._meta.fields)


admin.site.register(PaymentModel, PaymentModelAdmin)
admin.site.register(PaymentAttempt, PaymentAttemptAdmin)
admin.site.register(Refund, RefundAdmin)

@admin.register(PaymentResolution)
class PaymentResolutionAdmin(admin.ModelAdmin):
    action_form = PaymentResolutionActionForm
    list_display = (
        "id", "payment", "attempt", "reason", "status",
        "order_status_at_detection", "created_at", "resolved_at", "resolved_by",
    )
    list_filter = ("status", "reason", "created_at")
    search_fields = ("payment__id", "payment__order__id", "attempt__id")
    readonly_fields = (
        "payment", "attempt", "reason", "status", "order_status_at_detection",
        "created_at", "updated_at", "resolved_at", "resolved_by", "resolution_note",
    )
    actions = ("mark_resolved",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Resolve selected payment investigations with an audit note")
    def mark_resolved(self, request, queryset):
        note = (request.POST.get("resolution_note") or "").strip()
        if not note:
            self.message_user(
                request,
                "A resolution note is required; no records were changed.",
                level="error",
            )
            return
        resolved = 0
        for resolution_id in queryset.filter(
            status=PaymentResolutionStatus.OPEN
        ).values_list("pk", flat=True):
            try:
                PaymentResolutionService.resolve(
                    resolution_id=resolution_id,
                    actor=request.user,
                    note=note,
                )
            except Exception:
                logger.exception(
                    "Admin could not resolve PaymentResolution id=%s",
                    resolution_id,
                )
                self.message_user(
                    request,
                    f"Resolution {resolution_id} was not resolved; inspect application logs.",
                    level="error",
                )
            else:
                resolved += 1
        self.message_user(request, f"Resolved {resolved} payment resolution record(s).")
