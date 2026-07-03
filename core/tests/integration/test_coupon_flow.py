# tests/integration/test_coupon_flow.py
import pytest

from payment.services.payment_flow import (
    handle_successful_payment,
)


pytestmark = pytest.mark.django_db(transaction=True)


def test_coupon_used_after_success(
    session,
    coupon,
    successful_payment,
    mocker,
):
    verify = mocker.patch(
        "payment.services.payment_flow.verify_payment",
        return_value=successful_payment,
    )

    coupon.used_count = 0
    coupon.save()

    successful_payment.order.coupon = coupon
    successful_payment.order.save()

    handle_successful_payment(
        authority="AUTH",
        ref_id="REF",
        response={},
        session=session,
    )

    coupon.refresh_from_db()

    assert coupon.used_count == 1

    verify.assert_called_once()