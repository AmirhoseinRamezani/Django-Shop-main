# payment/services/services.py
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.core.exceptions import ValidationError
from payment.repositories.payment_repository import PaymentRepository
from payment.services.gateway_service import GatewayService

from payment.policies import PaymentPolicy
from order.events.order_event import OrderEventType
from order.services.events import record_order_event
from payment.services.factory import PaymentFactory
from django.utils.translation import gettext_lazy as _

class PaymentService:

    @staticmethod
    @transaction.atomic
    def start_payment(order):
        """
        Creates a new payment for an order and
        redirects user to gateway.
        """

        PaymentPolicy.can_start_payment(order)
        PaymentRepository.close_pending(order)
        
        # if not order.can_retry_payment():
        #     raise PermissionDenied(_("Payment is not allowed for this order"))

        # prevent duplicate pending payments
        # if order.payments.filter(status=PaymentStatusType.pending).exists():
        #     raise ValidationError(_("Pending payment already exists"))

        # zarinpal = ZarinPalSandbox()
        # response = zarinpal.payment_request(order.final_price)
        response = GatewayService.payment_request(order.final_price)

        payment = PaymentFactory.create(
            order=order,
            authority_id=response["Authority"],
            amount=order.final_price,
            request_payload=response,
            # response_json=response
        )
        record_order_event(
            order=order,
            type=OrderEventType.PAYMENT_STARTED,
            actor=order.user,
            payload={"amount": str(order.final_price)}
        )

        # order.status = OrderStatusType.pending
        # order.save(update_fields=[ "status"])

        # return zarinpal.generate_payment_url(payment.authority_id)
        return GatewayService.payment_url(
            response["Authority"],
        )
