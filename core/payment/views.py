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
from cart.models import CartModel

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
         # Lock related order
        order = payment.order

        # already finalized → SAFE EXIT
        if order.status == OrderStatusType.success:
            return redirect(reverse_lazy("order:completed"))
    
        # Already processed payment (idempotency)
        if payment.status != PaymentStatusType.pending.value:
            return redirect(
                reverse_lazy("order:completed")
                if payment.status == PaymentStatusType.success
                else reverse_lazy("order:failed")
            )

        # sanity check
        if payment.amount != order.get_price():
            payment.status = PaymentStatusType.failed
            order.status = OrderStatusType.failed
            payment.save(update_fields=["status"])
            order.save(update_fields=["status"])
            return redirect(reverse_lazy("order:failed"))

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
            payment.status = PaymentStatusType.success
            payment.ref_id = response.get("RefID")

            order.status = OrderStatusType.success

            # Consume coupon AFTER successful payment
            if order.coupon:
                order.coupon.mark_used()
            
            # clear cart (db + session)
            CartSession(request.session).clear()
            
            # clear coupon from session
            request.session.pop("coupon_id", None)
            request.session.modified = True
            
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
        
class RetryPaymentView(LoginRequiredMixin, View):
    """
    Safely retry payment for an order
    - Prevents double payment creation
    - Uses DB locking
    """
    @transaction.atomic
    def post(self, request, order_id):
        # Lock order row
        order = get_object_or_404(
            OrderModel.objects.select_for_update(),
            id=order_id,
            user=request.user
        )

        if not order.can_retry_payment():
            raise ValidationError("این سفارش قابل پرداخت مجدد نیست")

        # Prevent retry if a pending payment exists
        if order.payment and order.payment.status == PaymentStatusType.pending:
            raise ValidationError("پرداختی در حال انجام است")
        
        # expire old payment
        if order.payment:
            order.payment.status = PaymentStatusType.failed
            order.payment.save(update_fields=["status"])

        zarinpal = ZarinPalSandbox()
        response = zarinpal.payment_request(order.get_price())

        payment = PaymentModel.objects.create(
            authority_id=response["Authority"],
            amount=order.get_price(),
            status=PaymentStatusType.pending
        )

        order.payment = payment
        order.status = OrderStatusType.pending
        order.save(update_fields=["payment", "status"])

        return redirect(
            zarinpal.generate_payment_url(payment.authority_id)
        )
