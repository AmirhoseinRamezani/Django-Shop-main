# payments/views.py
from django.views import View
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.db import transaction
from django.core.exceptions import ValidationError
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import PaymentModel, PaymentStatusType
from .zarinpal_client import ZarinPalSandbox
from order.models import OrderModel, OrderStatusType
from cart.cart import CartSession
from payment.services.payment_flow import handle_successful_payment


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
        zarinpal = ZarinPalSandbox()
        response = zarinpal. verify_payment(
            int(payment.amount),
            payment.authority_id
        )
        
        # Save raw gateway response
        # payment.response_json = response
        # payment.response_code = response.get("Status")

        status_code = response.get("Status")

        if status_code in (100, 101):
            handle_successful_payment (
                authority=authority,
                ref_id=response.get("RefID"),
                response=response,
                session=request.session,
            )
            return redirect(reverse_lazy("order:completed"))

        payment.mark_failed(response=response)
        return redirect(reverse_lazy("order:failed"))
            
class RetryPaymentView(LoginRequiredMixin, View):

    @transaction.atomic
    def post(self, request, order_id):
        order = get_object_or_404(
            OrderModel.objects.select_for_update(),
            id=order_id,
            user=request.user
        )

        if not order.can_retry_payment():
            raise ValidationError("این سفارش قابل پرداخت مجدد نیست")

        if order.payments.filter(
            status=PaymentStatusType.pending
        ).exists():
            raise ValidationError("پرداختی در حال انجام است")

        # expire old payments
        order.payments.filter(
            status=PaymentStatusType.pending
        ).update(status=PaymentStatusType.failed)

        zarinpal = ZarinPalSandbox()
        response = zarinpal.payment_request(order.get_payable_price())

        payment = PaymentModel.objects.create(
            order=order,
            authority_id=response["Authority"],
            amount=order.get_payable_price(),
            status=PaymentStatusType.pending
        )

        return redirect(
            zarinpal.generate_payment_url(payment.authority_id)
        )
