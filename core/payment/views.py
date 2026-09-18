# payment/views.py
from django.views import View
from django.shortcuts import (
    get_object_or_404,
    redirect,
)
from django.urls import reverse, reverse_lazy

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
    Retry the existing Payment through a new PaymentAttempt.

    The view performs authentication/ownership and constructs the callback
    URL. Transaction boundaries and retry orchestration belong to the service.
    """

    def post(
        self,
        request,
        order_id,
        *args,
        **kwargs,
    ):
        order = get_object_or_404(
            OrderModel,
            pk=order_id,
            user=request.user,
        )

        callback_url = request.build_absolute_uri(
            reverse("payment:verify"),
        )

        payment_url = RetryPaymentService.retry(
            order=order,
            callback_url=callback_url,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )

        return redirect(payment_url)
