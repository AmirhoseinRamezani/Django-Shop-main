# core/order/services/confirm_payment.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from order.models import (
    OrderModel,
    OrderStatusType,
)
from order.services.coupon import CouponService
from order.services.state_machine import OrderStateMachine

from payment.enums import PaymentAttemptStatus, PaymentStatusType
from payment.exceptions import PaymentInvariantViolation
from payment.models import PaymentAttempt, PaymentModel
from payment.repositories.payment_repository import PaymentRepository


@transaction.atomic
def confirm_order_payment(
    order_id: int,
) -> OrderModel:
    """
    Finalize an Order after successful Payment.

    Lock hierarchy:

        Order
          ↓
        Payment
          ↓
        PaymentAttempt

    The service is transactional and idempotent.
    """

    # ----------------------------------------
    # 1. Lock Order
    # ----------------------------------------

    order = (
        OrderModel.objects
        .select_for_update()
        .get(pk=order_id)
    )

    if order.is_expired():
        raise ValidationError(
            _("Order expired")
        )

    # ----------------------------------------
    # 2. Lock latest successful Payment
    # ----------------------------------------

    payment = (
        PaymentModel.objects
        .select_for_update()
        .filter(
            order_id=order.pk,
            status=PaymentStatusType.SUCCESS,
        )
        .order_by(
            "-created_date",
            "-id",
        )
        .first()
    )

    if payment is None:
        raise ValidationError(
            _("No successful payment found")
        )

    # ----------------------------------------
    # 3. Idempotency
    # ----------------------------------------

    if payment.is_consumed:
        raise ValidationError(
            _("Payment already consumed")
        )

    # ----------------------------------------
    # 4. Lock successful PaymentAttempt
    # ----------------------------------------

    attempt = (
        PaymentAttempt.objects
        .select_for_update()
        .filter(
            payment_id=payment.pk,
            status=PaymentAttemptStatus.SUCCESS,
        )
        .order_by(
            "-attempt_number",
            "-id",
        )
        .first()
    )

    if attempt is None:
        raise ValidationError(
            _("No successful payment attempt found")
        )
        
    # Defensive aggregate consistency check.
    if attempt.payment_id != payment.pk:
        raise PaymentInvariantViolation(
            "PaymentAttempt does not belong to the expected Payment."
        )

    # ----------------------------------------
    # 5. Consume Payment
    # ----------------------------------------

    payment.consume()

    PaymentRepository.save(
        payment,
        update_fields=(
            "is_consumed",
        ),
    )

    # ----------------------------------------
    # 6. Synchronize Order
    # ----------------------------------------

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.paid,
        actor=order.user,
        payload={
            "payment_id": payment.pk,
            "attempt_id": attempt.pk,
            "ref_id": attempt.gateway_reference,
            "amount": str(payment.amount),
            "currency": str(payment.currency),
        },
    )

    # ----------------------------------------
    # 7. Coupon side effect
    # ----------------------------------------

    if order.coupon_id:
        CouponService.consume(
            order.coupon,
        )

    return order


# ----------------------------------------
# Backward-compatible adapter
# ----------------------------------------

def _confirm_order_payment(
    order_id: int,
) -> OrderModel:
    return confirm_order_payment(
        order_id=order_id,
    )