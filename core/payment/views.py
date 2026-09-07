# payment/views.py
from django.db import transaction

from django.views import View
from django.shortcuts import (
    get_object_or_404,
    redirect,
)
from django.urls import reverse_lazy

from django.contrib.auth.mixins import LoginRequiredMixin

from payment.exceptions import PaymentCallbackError, PaymentGatewayError
from payment.services.callback import resolve_payment_id

from payment.services.payment_flow import (
    handle_successful_payment,
)

from payment.services.retry import (
    RetryPaymentService,
)

from order.models import (
    OrderModel,
)


class PaymentVerifyView(View):
    """
    Gateway callback.

    Responsibilities

    - verify gateway callback
    - finalize payment
    - clear session cart

    Business logic lives inside services.
    """

    def get(
        self,
        request,
        *args,
        **kwargs,
    ):

        authority = request.GET.get("Authority")

        if not authority:
            return redirect(
                reverse_lazy("order:failed")
            )

        try:

            payment_id = resolve_payment_id(
                authority=authority,
            )
            
        except PaymentCallbackError:
            
            return redirect(
                reverse_lazy("order:failed")
            )
        
        try:
            handle_successful_payment(
                payment_id=payment_id,
                ref_id=request.GET.get("RefID"),
                response=request.GET.dict(),
                session=request.session,
            )
        except PaymentGatewayError as exc:
            # An unknown gateway outcome must not be presented as a confirmed
            # financial failure.  The authoritative service keeps Payment
            # pending and the exception is intentionally allowed to reach the
            # application's error handling / retry surface.
            if exc.retryable:
                raise

            return redirect(reverse_lazy("order:failed"))

        return redirect(reverse_lazy("order:completed"))


class RetryPaymentView(
    LoginRequiredMixin,
    View,
):
    """
    Restart payment for an existing order.

    Thin View.

    Responsibilities

    - authenticate user
    - lock order
    - ownership check
    - call RetryPaymentService
    - redirect to gateway
    """

    @transaction.atomic
    def post(
        self,
        request,
        order_id,
        *args,
        **kwargs,
    ):

        order = get_object_or_404(
            OrderModel.objects
            .select_for_update(),
            pk=order_id,
            user=request.user,
        )

        payment_url = RetryPaymentService.retry(
            order=order,
        )

        return redirect(payment_url)

