from django.core.exceptions import PermissionDenied
from django.db import transaction
from order.models import OrderStatusType
from django.core.exceptions import ValidationError
from payment.models import PaymentStatusType

from payment.models import PaymentModel
from payment.zarinpal_client import ZarinPalSandbox
from payment.policies import PaymentPolicy
from order.events.order_event import OrderEvent
from order.services.events import record_order_event

class PaymentService:

    @staticmethod
    @transaction.atomic
    def start_payment(order):
        """
        Creates a new payment for an order and
        redirects user to gateway.
        """

        PaymentPolicy.can_start_payment(order)
        
        if not order.can_retry_payment():
            raise PermissionDenied("Payment is not allowed for this order")

        # prevent duplicate pending payments
        if order.payments.filter(status=PaymentStatusType.pending).exists():
            raise ValidationError("Pending payment already exists")

        zarinpal = ZarinPalSandbox()
        response = zarinpal.payment_request(order.get_price())

        payment = PaymentModel.objects.create(
            order=order,
            authority_id=response["Authority"],
            amount=order.get_payable_price(),
            response_json=response
        )
        record_order_event(
            order=order,
            type=OrderEvent.PAYMENT_STARTED,
            actor=order.user,
            payload={"amount": str(order.get_payable_price())}
        )

        order.status = OrderStatusType.pending
        order.save(update_fields=[ "status"])

        return zarinpal.generate_payment_url(payment.authority_id)
