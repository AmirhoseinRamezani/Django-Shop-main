# payment/services/retry.py
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from order.models import OrderModel
from payment.models import PaymentModel

from payment.enums import PaymentStatusType
from payment.policies import PaymentPolicy
from payment.services.gateway_service import GatewayService
from order.events.order_event import OrderEventType
from order.services.events import record_order_event
from payment.services.factory import PaymentFactory
from payment.repositories.payment_repository import PaymentRepository


class RetryPaymentService:
    """
    Retry payment for an existing order.

    Responsibilities

    - lock order
    - validate retry
    - close previous pending payments
    - create new payment
    - emit event
    - return gateway url
    """

    @staticmethod
    @transaction.atomic
    def retry(
        *,
        order: OrderModel,
    ) -> str:

        order = (
            OrderModel.objects
            .select_for_update()
            .get(pk=order.pk)
        )

        if not order.can_retry_payment():
            raise ValidationError(
                _("This order cannot be paid again.")
            )

        # Close previous pending payments

        pending_payments = (
            PaymentRepository
            .pending(order)
            .select_for_update()

        )

        for payment in pending_payments:
            payment.mark_failed(
                response={
                    "reason": "payment_retry",
                }
            )
            
        latest_failed_payment = PaymentRepository.latest_failed(order)

        if latest_failed_payment is None:
            raise ValidationError(_("No failed payment found."))

        PaymentPolicy.can_retry(latest_failed_payment)

        # Request gateway
        response = GatewayService.payment_request(
            order.final_price,
        )

        payment = PaymentFactory.create(
            order=order,
            authority_id=response["Authority"],
            amount=order.final_price,
            gateway=PaymentRepository.default_gateway(order),
            request_payload=response,
            response_payload=response,
            status=PaymentStatusType.pending,
        )

        # Event
        record_order_event(
            order=order,
            type=OrderEventType.PAYMENT_RETRY,
            actor=order.user,
            payload={
                "payment_id": payment.id,
                "amount": str(payment.amount),
            },
        )

        return GatewayService.payment_url(
            payment.authority_id,
        )