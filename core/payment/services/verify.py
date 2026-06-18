from django.db import transaction
from django.core.exceptions import ValidationError

from payment.models import PaymentModel, PaymentStatusType
from order.services.confirm_payment import confirm_order_payment
from django.utils.translation import gettext_lazy as _

@transaction.atomic
def verify_payment(*, authority, ref_id, response=None):
    """
    Idempotent payment verification
    """

    payment = (
        PaymentModel.objects
        .select_for_update()
        .get(authority_id=authority)
    )

    if payment.status == PaymentStatusType.failed:
        raise ValidationError(_("Payment already failed"))

    # Gateway retry (safe)
    if payment.status == PaymentStatusType.success:
        return payment

    payment.mark_success(ref_id=ref_id, response=response)

    # confirm_order_payment(order_id=payment.order_id)

    return payment