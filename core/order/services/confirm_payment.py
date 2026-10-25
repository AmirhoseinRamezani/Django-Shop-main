# core/order/services/confirm_payment.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from order.events.order_event import OrderEventType
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
from payment.policies import PaymentPolicy

class OrderFinalizationConflict(ValidationError):
    """A recognized Order lifecycle conflict, distinct from financial errors."""

@transaction.atomic
def confirm_order_payment(
    order_id: int,
    payment_id: int | None = None,
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
        - resolve the exact successful Payment when payment_id is supplied
        - otherwise require a unique successful Payment for the Order
        - lock the Payment
        - resolve and lock its successful Attempt
        - consume the Payment
        - transition Order -> PAID
        - consume Coupon
        - commit everything atomically
    """

    # ===================================
    # 1. LOCK ORDER
    # ===================================

    order = (
        OrderModel.objects
        .select_for_update()
        .get(
            id=order_id,
        )
    )

    # ===================================
    # 2. ORDER VALIDATION
    # ===================================

    # Preserve idempotency for orders already finalized as PAID.
    # Other lifecycle conflicts should be rejected before payment lookup.
    if order.status != OrderStatusType.paid:
        if order.status == OrderStatusType.cancelled:
            raise OrderFinalizationConflict(_("Order is cancelled"))

        if order.status == OrderStatusType.failed:
            raise OrderFinalizationConflict(_("Order is failed"))

        if order.is_expired():
            raise OrderFinalizationConflict(_("Order expired"))


    # ===================================
    # 3. FIND LATEST SUCCESSFUL PAYMENT
    # ===================================

    successful_payments_query = (
        PaymentRepository
        .successful_for_order(order.id)
        .select_for_update()
    )

    if payment_id is not None:
        successful_payments_query = successful_payments_query.filter(
            pk=payment_id,
        )

    successful_payments = list(
        successful_payments_query.order_by(
            "-updated_date",
            "-id",
        )[:2]
    )

    if not successful_payments:
        raise ValidationError(
            _("No successful payment found")
        )

    if len(successful_payments) != 1:
        raise ValidationError(
            _("Multiple successful Payments found for Order")
        )

    payment = successful_payments[0]

    PaymentPolicy.validate_order_financial_snapshot(
        payment,
        order,
    )

    # ===================================
    # 4. PAYMENT IDEMPOTENCY
    # ===================================

    if payment.is_consumed:
        # Payment consumption and the Order transition are committed in the
        # same canonical transaction. Therefore an already-consumed Payment
        # is idempotently complete only when the Order is already PAID too.
        # Any other combination is a broken cross-aggregate invariant and
        # must not be silently repaired here.
        paid_event = (
            order.events
            .filter(type=OrderEventType.PAID)
            .order_by("-id")
            .first()
        )
        if (
            order.status == OrderStatusType.paid
            and paid_event is not None
            and paid_event.payload.get("payment_id") == payment.pk
        ):
            return order
        raise ValidationError(
            _("Consumed Payment is inconsistent with Order state or PAID event")
        )

    # ===================================
    # 5. PAYMENT -> EXACT PAYMENT ATTEMPT
    # ===================================

    successful_attempts = list(
        PaymentAttemptRepository
        .successful_for_payment(payment.id)
        .select_for_update()
        .order_by(
            "-attempt_number",
            "-id",
        )[:2]
    )

    if not successful_attempts:
        raise ValidationError(
            _("No successful payment attempt found")
        )

    if len(successful_attempts) != 1:
        raise ValidationError(
            _("Multiple successful payment attempts found for Payment")
        )

    attempt = successful_attempts[0]

    if attempt.payment_id != payment.id:
        raise ValidationError(
            _("Payment attempt does not belong to payment")
        )

    if attempt.status != PaymentAttemptStatus.SUCCESS:
        raise ValidationError(
            _("Payment attempt is not successful")
        )

    if not (
        attempt.gateway_reference
        or attempt.gateway_transaction_id
    ):
        raise ValidationError(
            _("Successful payment attempt has no gateway evidence")
        )

    # ===================================
    # 6. CONSUME PAYMENT
    # ===================================

    payment.consume()

    PaymentRepository.save(
        payment,
        update_fields=(
            "is_consumed",
        ),
    )

    # ===================================
    # 7. TRANSITION ORDER -> PAID
    # ===================================

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

    # ===================================
    # 8. CONSUME COUPON
    # ===================================

    if order.coupon_id:
        CouponService.consume(
            order.coupon,
        )

    # ===================================
    # 9. RETURN
    # ===================================

    return order


# =======================================
# LEGACY COMPATIBILITY ADAPTER
# =======================================

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