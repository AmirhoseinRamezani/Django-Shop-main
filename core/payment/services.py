from django.core.exceptions import PermissionDenied
from django.db import transaction
from order.models import OrderStatusType

from .models import PaymentModel
from .zarinpal_client import ZarinPalSandbox


class PaymentService:

    @staticmethod
    @transaction.atomic
    def start_payment(order):
        """
        Creates a new payment for an order and
        redirects user to gateway.
        """

        if not order.can_retry_payment():
            raise PermissionDenied("Payment is not allowed for this order")

        # prevent duplicate pending payments
        if order.payments.filter(status=1).exists():
            raise PermissionDenied("Pending payment already exists")

        zarinpal = ZarinPalSandbox()
        response = zarinpal.payment_request(order.get_price())

        payment = PaymentModel.objects.create(
            order=order,
            authority_id=response["Authority"],
            amount=order.get_payable_price(),
            response_json=response
        )

        order.status = OrderStatusType.pending
        order.save(update_fields=[ "status"])

        return zarinpal.generate_payment_url(payment.authority_id)
