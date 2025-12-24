from django.views import View
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.db import transaction

from .models import PaymentModel, PaymentStatusType
from .zarinpal_client import ZarinPalSandbox
from order.models import OrderModel, OrderStatusType


class PaymentVerifyView(View):
    """
    Single source of truth for payment verification.
    Responsible for:
    - Verifying payment with gateway
    - Updating payment & order status
    - Consuming coupon (if exists)
    """

    @transaction.atomic
    def get(self, request, *args, **kwargs):
        authority = request.GET.get("Authority")

        # Invalid callback
        if not authority:
            return redirect(reverse_lazy("order:failed"))

        # Lock payment row
        payment = get_object_or_404(
            PaymentModel.objects.select_for_update(),
            authority_id=authority
        )

        # Already processed payment (idempotency)
        if payment.status != PaymentStatusType.pending.value:
            return redirect(
                reverse_lazy("order:completed")
                if payment.status == PaymentStatusType.success
                else reverse_lazy("order:failed")
            )

        # Lock related order
        order = get_object_or_404(
            OrderModel.objects.select_for_update(),
            payment=payment
        )

        zarinpal = ZarinPalSandbox()
        response = zarinpal.payment_verify(
            int(payment.amount),
            payment.authority_id
        )

        # Save raw gateway response
        payment.response_json = response
        payment.response_code = response.get("Status")

        if response.get("Status") in (100, 101):
            # SUCCESS
            payment.status = PaymentStatusType.success.value
            payment.ref_id = response.get("RefID")

            order.status = OrderStatusType.success.value

            # Consume coupon AFTER successful payment
            if order.coupon:
                order.coupon.mark_used()

            redirect_url = reverse_lazy("order:completed")

        else:
            # FAILED
            payment.status = PaymentStatusType.failed.value
            order.status = OrderStatusType.failed.value
            redirect_url = reverse_lazy("order:failed")

        payment.save(update_fields=[
            "status",
            "ref_id",
            "response_json",
            "response_code",
        ])
        order.save(update_fields=["status"])

        return redirect(redirect_url)
        
