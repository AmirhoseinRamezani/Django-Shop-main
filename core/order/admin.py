from secrets import token_urlsafe

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    CouponModel,
    OrderItemModel,
    OrderModel,
    UserAddressModel,
)
from payment.exceptions import (
    PaymentCurrencyMismatchError,
    PaymentInvariantViolation,
    PaymentRefundAmountInvalidError,
)
from payment.repositories.payment_repository import PaymentRepository
from payment.services.refund import RefundService


class OrderItemInline(admin.TabularInline):
    model = OrderItemModel
    extra = 0
    readonly_fields = ("product", "quantity", "price")


@admin.register(OrderModel)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "full_name",
        "phone",
        "total_price",
        "status",
        "sale_type",
        "created_date",
        "refund_action",
    )
    list_filter = ("status", "sale_type")
    search_fields = ("full_name", "phone", "email")
    readonly_fields = tuple(field.name for field in OrderModel._meta.fields)
    inlines = (OrderItemInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        info = self.opts.app_label, self.opts.model_name
        custom_urls = [
            path(
                "<path:object_id>/refund/",
                self.admin_site.admin_view(self.refund_view),
                name="%s_%s_refund" % info,
            ),
        ]
        return custom_urls + super().get_urls()

    def refund_action(self, obj):
        if obj.can_refund():
            url = reverse(
                "admin:%s_%s_refund"
                % (self.opts.app_label, self.opts.model_name),
                args=[obj.pk],
            )
            return format_html('<a href="{}">Refund</a>', url)
        return "-"

    refund_action.short_description = "Refund"

    def refund_view(self, request, object_id):
        if not request.user.is_authenticated or not request.user.is_staff:
            raise PermissionDenied("Admin access required")

        order = get_object_or_404(OrderModel, pk=object_id)
        payment = PaymentRepository.latest_successful_for_order(order.pk)

        if payment is None:
            raise Http404("No successful Payment exists for this Order.")

        if request.method == "GET":
            request.current_app = self.admin_site.name
            return TemplateResponse(
                request,
                "admin/order/order_refund_confirm.html",
                {
                    **self.admin_site.each_context(request),
                    "title": "Confirm Order Refund",
                    "order": order,
                    "payment": payment,
                    "idempotency_key": "admin-" + token_urlsafe(24),
                    "opts": self.opts,
                },
            )

        if request.method != "POST":
            raise PermissionDenied("POST required")

        idempotency_key = request.POST.get("idempotency_key", "").strip()
        if not idempotency_key:
            self.message_user(
                request,
                "Refund idempotency key is required.",
                messages.ERROR,
            )
            return redirect(
                "admin:%s_%s_changelist"
                % (self.opts.app_label, self.opts.model_name)
            )

        try:
            refund = RefundService.refund_order(
                order_id=order.pk,
                payment_id=payment.pk,
                actor=request.user,
                idempotency_key=idempotency_key,
            )
        except (
            PaymentCurrencyMismatchError,
            PaymentInvariantViolation,
            PaymentRefundAmountInvalidError,
        ) as exc:
            self.message_user(request, str(exc), messages.ERROR)
        else:
            self.message_user(
                request,
                f"Refund #{refund.pk} is {refund.get_status_display()}.",
                messages.SUCCESS if refund.is_success else messages.WARNING,
            )

        return redirect(
            "admin:%s_%s_changelist"
            % (self.opts.app_label, self.opts.model_name)
        )

    def final_price(self, obj):
        return obj.get_price()

    final_price.short_description = "مبلغ نهایی"

    def has_coupon(self, obj):
        return bool(obj.coupon_code)

    has_coupon.boolean = True
    has_coupon.short_description = "کوپن؟"


@admin.register(CouponModel)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "discount_percent",
        "used_count",
        "max_limit_usage",
        "is_active",
        "expiration_date",
    )
    list_filter = ("is_active",)
    search_fields = ("code",)


@admin.register(UserAddressModel)
class UserAddressAdmin(admin.ModelAdmin):
    list_display = ("user", "city", "state", "zip_code")
    search_fields = ("user__username", "city")
