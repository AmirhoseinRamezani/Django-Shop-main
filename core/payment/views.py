from django.views import View
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.db import transaction

from .models import PaymentModel, PaymentStatusType
from .zarinpal_client import ZarinPalSandbox
from order.models import OrderModel, OrderStatusType


class PaymentVerifyView(View):
    """
    Verify payment callback from payment gateway.
    This view is idempotent and transaction-safe.
    """

    @transaction.atomic
    def get(self, request):
        authority = request.GET.get("Authority")

        # Invalid callback request
        if not authority:
            return redirect(reverse_lazy("order:failed"))

        # Lock payment row to prevent double verification
        payment = get_object_or_404(
            PaymentModel.objects.select_for_update(),
            authority_id=authority
        )

        # Payment already processed
        if payment.status != PaymentStatusType.pending.value:
            return redirect(reverse_lazy("order:completed"))

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

        # Save raw response for audit/debug
        payment.response_json = response
        payment.response_code = response.get("Status")

        if response.get("Status") in (100, 101):
            payment.status = PaymentStatusType.success.value
            payment.ref_id = response.get("RefID")
            order.status = OrderStatusType.success.value
        else:
            payment.status = PaymentStatusType.failed.value
            order.status = OrderStatusType.failed.value

        payment.save()
        order.save()

        return redirect(
            reverse_lazy("order:completed")
            if payment.status == PaymentStatusType.success.value
            else reverse_lazy("order:failed")
        )
