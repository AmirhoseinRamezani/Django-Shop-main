# order/services/confirm_payment.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from order.events.order_event import OrderEventType
from order.models import OrderModel, OrderStatusType
from order.services.coupon import CouponService
from order.services.state_machine import OrderStateMachine

from payment.enums import PaymentAttemptStatus
from payment.policies import PaymentPolicy
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from payment.repositories.payment_repository import PaymentRepository


class OrderFinalizationConflict(ValidationError):
    """A recognized Order lifecycle conflict."""


@transaction.atomic
def confirm_order_payment(
    order_id: int,
    payment_id: int | None = None,
) -> OrderModel:
    """
    Finalize an Order after a successful Payment.

    Lock hierarchy:
        Order -> Payment -> PaymentAttempt

    The entire financial finalization is committed atomically.
    """

    # ==========================================================
    # 1. LOCK ORDER
    # ==========================================================

    order = (
        OrderModel.objects
        .select_for_update()
        .get(pk=order_id)
    )

    # ==========================================================
    # 2. ORDER LIFECYCLE VALIDATION
    # ==========================================================

    # Expiration is an Order-local precondition and must remain the
    # earliest rejection. In particular, an expired Order must not
    # perform any Payment lookup or mutation.
    if (
        order.status != OrderStatusType.paid
        and order.is_expired()
    ):
        raise OrderFinalizationConflict(
            _("Order expired")
        )

    # Terminal lifecycle conflicts for cancelled/failed Orders and a
    # competing unconsumed Payment on an already-paid Order are checked
    # only after the Payment financial evidence has been established.
    # This prevents verify/reconciliation from converting missing attempt
    # or financial-snapshot failures into terminal Order resolutions.

    # ==========================================================
    # 3. RESOLVE EXACT PAYMENT
    # ==========================================================

    if payment_id is not None:
    
        # An explicit payment id is authoritative for this finalization.
        # Never discover a different successful Payment and then compare ids.
        # The canonical Payment aggregate lock is acquired immediately.
        try:
            payment = PaymentRepository.get_for_update(payment_id)
        except PaymentRepository.model.DoesNotExist:
            raise ValidationError(
                _("No successful payment found")
            )

        if payment.order_id != order.pk:
            raise ValidationError(
                _("No successful payment found")
            )

        if not payment.is_successful:
            raise ValidationError(
                _("No successful payment found")
            )
    else:
        # Order-only confirmation is valid only when the Order has exactly
        # one successful Payment. There is intentionally no fallback to
        # latest/first successful Payment selection.
        successful_payments = list(
            PaymentRepository
            .successful_for_order(order.pk)
            .select_for_update()
            .order_by(
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
    # ==========================================================
    # 4. PAYMENT ↔ ORDER FINANCIAL IDENTITY
    # ==========================================================
    if payment.order_id != order.pk:
        raise ValidationError(
            _("Payment does not belong to Order")
        )
    PaymentPolicy.validate_order_financial_snapshot(
        payment,
        order,
    )

    # ==========================================================
    # 5. RESOLVE EXACT SUCCESSFUL PAYMENT ATTEMPT
    # ==========================================================
    # A consumed Payment may only be treated as idempotently finalized when
    # its current financial evidence still resolves to exactly one successful
    # PaymentAttempt. The idempotency branch must not bypass this identity
    # boundary.
    successful_attempts = list(
        PaymentAttemptRepository
        .successful_for_payment(payment.pk)
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

    if attempt.payment_id != payment.pk:
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

    # ==========================================================
    # 6. IDEMPOTENT PAYMENT CONSUMPTION
    # ==========================================================

    if payment.is_consumed:
        paid_event = (
            order.events
            .filter(type=OrderEventType.PAID)
            .order_by("-id")
            .first()
        )

        event_attempt_id = (
            paid_event.payload.get("attempt_id")
            if paid_event is not None
            else None
        )

        if (
            order.status == OrderStatusType.paid
            and paid_event is not None
            and paid_event.payload.get("payment_id") == payment.pk
            and event_attempt_id == attempt.pk
        ):
            if order.coupon_id:
                CouponService.schedule_reconciliation(order.pk)
            return order

        raise ValidationError(
            _(
                "Consumed Payment is inconsistent with "
                "Order state or PAID event"
            )
         )
    # ==========================================================
    # 7. TERMINAL ORDER CONFLICTS
    # ==========================================================

    if order.status == OrderStatusType.cancelled:
        raise OrderFinalizationConflict(
            _("Order is cancelled")
        )

    if order.status == OrderStatusType.failed:
        raise OrderFinalizationConflict(
            _("Order is failed")
        )

    if order.status == OrderStatusType.paid:
        # An already-consumed Payment with its matching PAID event was
        # handled by the idempotency branch above. Therefore reaching this
        # point means this is a distinct successful Payment attempting to
        # finalize an already-paid Order.
        raise OrderFinalizationConflict(
            _("Order already paid")
        )

    # ==========================================================
    # 8. CONSUME PAYMENT
    # ==========================================================

    payment.consume()

    PaymentRepository.save(
        payment,
        update_fields=("is_consumed",),
    )

    # ==========================================================
    # 9. TRANSITION ORDER -> PAID
    # ==========================================================

    order = OrderStateMachine.transition(
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

    # ==========================================================
    # 10. SCHEDULE COUPON RECONCILIATION
    # ==========================================================

    # The PAID event and consumed Payment are the durable success evidence.
    # Coupon accounting runs only after this transaction commits, so a coupon
    # persistence failure cannot roll back verified financial finalization.
    if order.coupon_id:
        CouponService.schedule_reconciliation(order.pk)

    return order
