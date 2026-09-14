# payment/views.py
from django.db import transaction

from django.views import View
from django.shortcuts import (
    get_object_or_404,
    redirect,
)
from django.urls import reverse_lazy

from django.contrib.auth.mixins import LoginRequiredMixin

from payment.exceptions import (
    PaymentCallbackError,
    PaymentGatewayError,
    PaymentCallbackIdentityMismatchError,
)
from payment.services.callback import resolve_callback
from payment.services.gateway_service import GatewayService

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
        payload = request.GET.dict()
        authority = request.GET.get("Authority")

        if not authority:
            return redirect(
                reverse_lazy("order:failed")
            )

        try:
            resolution = resolve_callback(
                authority=authority,
            )

            callback = GatewayService.parse_callback(
                payload=payload,
                gateway=resolution.gateway,
            )

            callback_authority = str(
                callback.authority or ""
            ).strip()

            if callback_authority != resolution.authority:
                raise PaymentCallbackIdentityMismatchError(
                    "Parsed gateway callback authority does not match "
                    "the resolved PaymentAttempt."
                )

            handle_successful_payment(
                payment_id=resolution.payment_id,
                attempt_id=resolution.attempt_id,
                ref_id=request.GET.get("RefID"),
                response=payload,
                session=request.session,
            )

        except PaymentCallbackError:
            return redirect(
                reverse_lazy("order:failed")
            )

        except PaymentGatewayError as exc:
            # A transport/unknown gateway outcome must never be presented
            # as a confirmed financial failure.  The authoritative service
            # leaves the Payment pending for later reconciliation.
            if exc.retryable:
                raise

            return redirect(
                reverse_lazy("order:failed")
            )

        return redirect(
            reverse_lazy("order:completed")
        )



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

