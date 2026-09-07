# payment/services/payment_flow.py

from payment.services.verify import verify_payment
from cart.cart import CartSession

def handle_successful_payment(
    *,
    payment_id,
    ref_id=None,
    response=None,
    session,
):
    """Verify a Payment and perform presentation/session side effects.

    This is no longer a second payment implementation.  All financial
    verification and lifecycle mutation belongs to ``verify_payment``.
    """
    payment = verify_payment(
        payment_id=payment_id,
        ref_id=ref_id,
        response=response,
    )

    order = payment.order

    CartSession(session).clear()
    session.pop("coupon_id", None)
    session.modified = True

    return order