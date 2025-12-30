from django.db import transaction
from django.core.exceptions import ValidationError

from payment.models import PaymentModel, PaymentStatusType
from order.services.confirm_payment import confirm_order_payment


def verify_payment(*, authority, ref_id):
    """
    Idempotent payment verification
    """

    with transaction.atomic():
        payment = (
            PaymentModel.objects
            .select_for_update()
            .get(authority=authority)
        )

        # If Already Successful, Do Nothing
        if payment.status == PaymentStatusType.success:
            return payment

        # Previous Failed Payment → Don't Allow to Continue
        if payment.status == PaymentStatusType.failed:
            raise ValidationError("Payment already failed")

        # Register Payment
        payment.mark_success(ref_id=ref_id)

        #  Finalize Order
        confirm_order_payment(payment.order_id)

    return payment
