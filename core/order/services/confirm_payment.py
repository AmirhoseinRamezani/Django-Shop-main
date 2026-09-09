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

from payment.enums import (
    PaymentAttemptStatus,
    PaymentStatusType,
)
from payment.models import PaymentModel
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from payment.repositories.payment_repository import (
    PaymentRepository,
)


@transaction.atomic
def confirm_order_payment(
    order_id: int,
) -> OrderModel:
    """
    Finalize an Order after a successful Payment.

    Transaction boundary:
        Order
            ->
        Payment
            ->
        PaymentAttempt

    Responsibilities:
        - lock the Order
        - find the latest successful Payment
        - lock the Payment
        - resolve and lock its successful Attempt
        - consume the Payment
        - transition Order -> PAID
        - consume Coupon
        - commit everything atomically
    """

    # ============================================================
    # 1. LOCK ORDER
    # ============================================================

    order = (
        OrderModel.objects
        .select_for_update()
        .get(
            id=order_id,
        )
    )

    # ============================================================
    # 2. ORDER VALIDATION
    # ============================================================

    if order.is_expired():
        raise ValidationError(
            _("Order expired")
        )

    # ============================================================
    # 3. FIND LATEST SUCCESSFUL PAYMENT
    # ============================================================

    payment = (
        PaymentRepository
        .successful_for_order(order.id)
        .select_for_update()
        .order_by(
            "-updated_date",
            "-id",
        )
        .first()
    )

    if payment is None:
        raise ValidationError(
            _("No successful payment found")
        )

    # ============================================================
    # 4. PAYMENT IDEMPOTENCY
    # ============================================================

    if payment.is_consumed:
        raise ValidationError(
            _("Payment has already been consumed")
        )

    # ============================================================
    # 5. PAYMENT -> ATTEMPT
    # ============================================================

    attempt = (
        PaymentAttemptRepository
        .successful_for_payment(payment.id)
        .select_for_update()
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

    if attempt.payment_id != payment.id:
        raise ValidationError(
            _("Payment attempt does not belong to payment")
        )

    if (
        attempt.status
        != PaymentAttemptStatus.SUCCESS
    ):
        raise ValidationError(
            _("Payment attempt is not successful")
        )

    # ============================================================
    # 6. CONSUME PAYMENT
    # ============================================================

    payment.consume()

    PaymentRepository.save(
        payment,
        update_fields=(
            "is_consumed",
        ),
    )

    # ============================================================
    # 7. TRANSITION ORDER -> PAID
    # ============================================================

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.paid,
        actor=order.user,
        payload={
            "payment_id": payment.id,
            "attempt_id": attempt.id,
            "ref_id": attempt.gateway_reference,
            "amount": str(payment.amount),
            "currency": str(payment.currency),
        },
    )

    # ============================================================
    # 8. CONSUME COUPON
    # ============================================================

    if order.coupon_id:
        CouponService.consume(
            order.coupon,
        )

    # ============================================================
    # 9. RETURN
    # ============================================================

    return order


# ================================================================
# LEGACY COMPATIBILITY ADAPTER
# ================================================================

def _confirm_order_payment(
    order_id: int,
) -> OrderModel:
    """
    Backward-compatible adapter.

    The canonical implementation remains
    confirm_order_payment().
    """

    payment_exists = (
        PaymentRepository
        .successful_for_order(order_id)
        .exists()
    )

    if not payment_exists:
        raise ValidationError(
            _("No successful payment found")
        )

    return confirm_order_payment(
        order_id,
    )