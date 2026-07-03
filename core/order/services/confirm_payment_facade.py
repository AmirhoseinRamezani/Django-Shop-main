# order/services/confirm_payment_facade.py
from django.core.exceptions import ValidationError
from payment.models import PaymentModel

from .confirm_payment import confirm_order_payment
from django.utils.translation import gettext as _

def confirm_order_payment_by_order_id(order_id: int):
    try:
        payment = (
            PaymentModel.objects
            .filter(order_id=order_id)
            .latest("created_date")
        )
    except PaymentModel.DoesNotExist:
        raise ValueError(_("No payment found for this order"))

    try:
        return confirm_order_payment(order_id=payment.order_id)
    except ValidationError as e:
        raise ValueError(str(e))
