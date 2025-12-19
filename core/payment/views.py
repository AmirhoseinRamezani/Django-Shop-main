from django.views import View
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.db import transaction

from .models import PaymentModel, PaymentStatusType
from .zarinpal_client import ZarinPalSandbox
from order.models import OrderModel, OrderStatusType


class PaymentVerifyView(View):
    @transaction.atomic
    def get(self, request):
        authority = request.GET.get("Authority")

        payment = get_object_or_404(PaymentModel, authority_id=authority)
        order = get_object_or_404(OrderModel, payment=payment)

        if payment.status != PaymentStatusType.pending:
            return redirect(reverse_lazy("order:completed"))

        zarinpal = ZarinPalSandbox()
        response = zarinpal.payment_verify(
            int(payment.amount),
            payment.authority_id
        )

        payment.response_json = response
        payment.response_code = response.get("Status")

        if response.get("Status") in (100, 101):
            payment.status = PaymentStatusType.success
            payment.ref_id = response.get("RefID")
            order.status = OrderStatusType.success
        else:
            payment.status = PaymentStatusType.failed
            order.status = OrderStatusType.failed

        payment.save()
        order.save()

        return redirect(
            reverse_lazy("order:completed")
            if payment.status == PaymentStatusType.success
            else reverse_lazy("order:failed")
        )
