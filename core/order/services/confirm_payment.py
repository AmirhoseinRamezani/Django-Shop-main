# order/services/confirm_payment.py
from django.db import transaction
from django.core.exceptions import ValidationError

from order.services.state_machine import OrderStateMachine
from order.models import OrderModel, OrderStatusType,CouponModel
from payment.models import PaymentModel
from payment.enums import PaymentStatusType
from order.events.order_event import OrderEventType
from order.services.events import record_order_event
from django.utils.translation import gettext as _
from django.db.models import F

@transaction.atomic
def confirm_order_payment(order_id: int) -> OrderModel:  #*, payment
    """
    Finalize order after successful payment.
    Atomic & idempotent.
    """
    # Lock order
    order = (
        OrderModel.objects
        .select_for_update()
        .get(id=order_id)
    )

    # Order expired
    if order.is_expired():
        raise ValidationError(_("Order expired"))

    # Find latest successful payment
    payment = (
        PaymentModel.objects
        .select_for_update()
        .filter(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )
        .order_by("-created_date")
        .first()
    )

    if not payment:
        raise ValidationError(_("No successful payment found"))

    # Idempotency
    if payment.is_consumed:
        raise ValidationError(_("Payment already consumed"))

    # Finalize
    # payment.is_consumed = True
    payment.consume()
    # payment.save(update_fields=["is_consumed"])


    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.paid,
        actor=order.user,
        payload={
            "payment_id": payment.id,
            "ref_id": payment.ref_id,
            "amount": str(order.final_price),
        }
    )
    
    
    # CouponService.consume_coupon()
    
    # CouponModel.objects.filter(
    #     pk=order.coupon_id
    # ).update(
    #     used_count=F("used_count")+1
    # )
    
    if order.coupon:
        CouponService.consume(order.coupon)
    
    
    # record_order_event(
    #     order=order,
    #     type=OrderEventType.PAID,
    #     actor=order.user,
    #     payload={
    #         "payment_id": payment.id,
    #         "ref_id": payment.ref_id,
    #         "amount": str(order.final_price()),
    #     },
    # )

    return order

# -----------------------------
# Public API (backward compatible)
# -----------------------------
def _confirm_order_payment(order_id: int) -> OrderModel:
    """
    Adapter for legacy calls & tests.
    """
    payment = (
        PaymentModel.objects
        .filter(
            order_id=order_id,
            status=PaymentStatusType.SUCCESS,
        )
        .order_by("-created_date")
        .first()
    )

    if not payment:
        raise ValidationError(_("No successful payment found"))

    return confirm_order_payment(order_id) # = order_id