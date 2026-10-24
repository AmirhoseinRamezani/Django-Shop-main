# order/services/confirm_payment_facade.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from payment.enums import PaymentStatusType
from payment.repositories.payment_repository import PaymentRepository

from .confirm_payment import confirm_order_payment


def confirm_order_payment_by_order_id(order_id: int):
    """
    Backward-compatible Order-based confirmation adapter.

    The adapter must never select an arbitrary Payment.

    Resolution contract:
        Order
          -> exactly one successful Payment
          -> exact payment_id
          -> canonical confirmation service

    The canonical service remains responsible for:
        - locking the Order
        - locking the exact Payment
        - validating Payment -> Order identity
        - resolving the successful PaymentAttempt
        - consuming the Payment
        - transitioning the Order
        - consuming the Coupon
        - atomic transaction semantics
    """

    successful_payments = list(
        PaymentRepository
        .successful_for_order(order_id)
        .order_by("id")[:2]
    )

    if not successful_payments:
        raise ValueError(
            _("No successful payment found for this order")
        )

    if len(successful_payments) != 1:
        raise ValueError(
            _("Multiple successful Payments found for this order")
        )

    payment = successful_payments[0]

    try:
        return confirm_order_payment(
            order_id=order_id,
            payment_id=payment.pk,
        )
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc