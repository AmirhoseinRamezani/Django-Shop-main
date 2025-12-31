# order/services/confirm_payment.py

from django.db import transaction
from django.core.exceptions import ValidationError

from order.models import OrderModel, OrderStatusType
from payment.models import PaymentStatusType
from order.events.order_event import OrderEventType
from order.services.events import record_order_event

@transaction.atomic
def confirm_order_payment(*, payment):
    """
    Finalize order after successful payment.
    Atomic & idempotent.
    """
    payment = (
        payment.__class__.objects
        .select_for_update()
        .select_related("order")
        .get(id=payment.id)
    )

    order = payment.order

    # Already consumed → SAFE EXIT
    if payment.is_consumed:
        return order

    # Payment must be successful
    if payment.status != PaymentStatusType.success:
        raise ValidationError("Payment is not successful")

    # Order already finalized → consume payment & exit
    if order.status == OrderStatusType.success:
        payment.is_consumed = True
        payment.save(update_fields=["is_consumed"])
        return order

    if order.is_expired():
        raise ValidationError("Order expired")

    # ---- FINALIZE ----
    payment.is_consumed = True
    payment.save(update_fields=["is_consumed"])

    order.status = OrderStatusType.success
    order.save(update_fields=["status"])

    record_order_event(
        order=order,
        type=OrderEventType.PAID,
        actor=order.user,
        payload={
            "payment_id": payment.id,
            "ref_id": payment.ref_id,
            "amount": str(payment.amount),
        },
    )

    return order