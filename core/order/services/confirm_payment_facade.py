# order/services/confirm_payment_facade.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from .confirm_payment import confirm_order_payment


def confirm_order_payment_by_order_id(order_id: int):
    """
    Backward-compatible Order-based confirmation adapter.

    The canonical confirmation service owns Payment resolution. Keeping the
    adapter free of Payment discovery is important because discovery must
    happen only after the Order row has been locked.

    The canonical service remains responsible for:
        - locking the Order
        - locking the exact Payment
        - validating Payment -> Order identity
        - resolving the successful PaymentAttempt
        - consuming the Payment
        - transitioning the Order
        - consuming the Coupon
        - atomic transaction semantics
        
    ValidationError is translated to the historical ValueError contract of
    this backward-compatible adapter.
    """

    try:
        return confirm_order_payment(order_id=order_id)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc