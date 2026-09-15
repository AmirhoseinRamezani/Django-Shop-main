# core/payment/services/payment_flow.py

from __future__ import annotations

from typing import Any

from cart.cart import CartSession
from payment.services.verify import verify_payment


def handle_successful_payment(
    *,
    payment_id: int,
    attempt_id: int | None = None,
    ref_id: str | None = None,
    response: dict[str, Any] | None = None,
    session,
):
    """Verify a gateway callback and apply presentation-side effects.

    Financial mutation remains exclusively inside ``verify_payment``.
    ``attempt_id`` is optional for internal/direct callers, but canonical
    gateway callbacks should always pass the attempt resolved from the
    callback authority.
    """

    verify_kwargs = {
        "payment_id": payment_id,
        "ref_id": ref_id,
        "response": response,
    }

    if attempt_id is not None:
        verify_kwargs["attempt_id"] = attempt_id

    payment = verify_payment(**verify_kwargs)

    order = payment.order

    CartSession(session).clear()
    session.pop("coupon_id", None)
    session.modified = True

    return order
