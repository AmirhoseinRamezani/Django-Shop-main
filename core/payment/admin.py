# core/payment/admin.py
from django.contrib import admin

from payment.models import PaymentAttempt, PaymentModel, Refund


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
