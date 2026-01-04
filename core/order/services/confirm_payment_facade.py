# order/services/confirm_payment_facade.py

from django.core.exceptions import ValidationError
from payment.models import PaymentModel

from .confirm_payment import confirm_order_payment


def confirm_order_payment_by_order_id(order_id: int):
    try:
        payment = (
            PaymentModel.objects
            .filter(order_id=order_id)
            .latest("created_date")
        )
    except PaymentModel.DoesNotExist:
        raise ValueError("No payment found for this order")

    try:
        return confirm_order_payment(payment=payment)
    except ValidationError as e:
        raise ValueError(str(e))
