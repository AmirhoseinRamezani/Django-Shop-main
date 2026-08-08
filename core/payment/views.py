# payment/views.py
from django.db import transaction

from django.views import View
from django.shortcuts import (
    get_object_or_404,
    redirect,
)
from django.urls import reverse_lazy

from django.contrib.auth.mixins import LoginRequiredMixin

from django.core.exceptions import (
    ValidationError,
)

from payment.models import (
    PaymentAttempt,
)

from payment.services.gateway_service import (
    GatewayService,
)

from payment.services.payment_flow import (
    handle_successful_payment,
)

from payment.services.retry import (
    RetryPaymentService,
)

from payment.services.services import (
    PaymentService,
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

    @transaction.atomic
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

        attempt = get_object_or_404(
            PaymentAttempt.objects.select_for_update(),
            authority_id=authority,
        )

        payment = attempt.payment

        response = GatewayService.verify(attempt)

        PaymentService.complete(
            payment=payment,
            attempt=attempt,
            gateway_response=response,
        )

        try:

            handle_successful_payment(
                authority=authority,
                ref_id=response.get("RefID"),
                response=response,
                session=request.session,
            )

            return redirect(
                reverse_lazy("order:completed")
            )

        except ValidationError:

            payment.mark_failed(
                response=response,
            )

            return redirect(
                reverse_lazy("order:failed")
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

