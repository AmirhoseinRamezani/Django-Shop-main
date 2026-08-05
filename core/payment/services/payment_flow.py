# payment/services/payment_flow.py

from django.db import transaction

from payment.services.verify import verify_payment
from cart.cart import CartSession

def handle_successful_payment(*, authority, ref_id, response, session):
    payment = verify_payment(
        authority=authority,
        ref_id=ref_id,
        response=response,
    )

    order = payment.order

    # if order.coupon:
    #     order.coupon.mark_used()

    CartSession(session).clear()
    session.pop("coupon_id", None)
    session.modified = True

    return order