# core/order/services/confirm_payment.py
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

    if order.status != OrderStatusType.paid:
        if order.status == OrderStatusType.cancelled:
            raise OrderFinalizationConflict(
                _("Order is cancelled")
            )

        if order.status == OrderStatusType.failed:
            raise OrderFinalizationConflict(
                _("Order is failed")
            )

        if order.is_expired():
            raise OrderFinalizationConflict(
                _("Order expired")
            )

    # ==========================================================
    # 3. RESOLVE SUCCESSFUL PAYMENT
    # ==========================================================

    successful_payments = list(
        PaymentRepository
        .successful_for_order(order.pk)
        .select_for_update()
        .order_by(
            "-updated_date",
            "-id",
        )[:2]
    )

    if payment_id is not None:
        successful_payments = [
            payment
            for payment in successful_payments
            if payment.pk == payment_id
        ]

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

    PaymentPolicy.validate_order_financial_snapshot(
        payment,
        order,
    )

    # ==========================================================
    # 5. IDEMPOTENT PAYMENT CONSUMPTION
    # ==========================================================

    if payment.is_consumed:
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
            _(
                "Consumed Payment is inconsistent with "
                "Order state or PAID event"
            )
        )

    # ==========================================================
    # 6. RESOLVE EXACT SUCCESSFUL PAYMENT ATTEMPT
    # ==========================================================

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
    # 7. CONSUME PAYMENT
    # ==========================================================

    payment.consume()

    PaymentRepository.save(
        payment,
        update_fields=("is_consumed",),
    )

    # ==========================================================
    # 8. TRANSITION ORDER -> PAID
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
    # 9. CONSUME COUPON
    # ==========================================================

    if order.coupon_id:
        CouponService.consume(order.coupon)

    return order

# # =======================================
# # LEGACY COMPATIBILITY ADAPTER
# # =======================================

# def _confirm_order_payment(
#     order_id: int,
# ) -> OrderModel:
#     """
#     Backward-compatible adapter.

#     The canonical implementation remains
#     confirm_order_payment().
#     """

#     payment_exists = (
#         PaymentRepository
#         .successful_for_order(order_id)
#         .exists()
#     )

#     if not payment_exists:
#         raise ValidationError(
#             _("No successful payment found")
#         )

#     return confirm_order_payment(
#         order_id,
#     )