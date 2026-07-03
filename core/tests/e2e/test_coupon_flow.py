# tests/e2e/test_coupon_flow.py
import pytest

from payment.services.payment_flow import handle_successful_payment


pytestmark = pytest.mark.django_db


class DummySession(dict):

    modified = False


def test_coupon_consumed_after_payment(
    successful_payment,
    coupon,
):

    order = successful_payment.order

    order.coupon = coupon
    order.save(update_fields=["coupon"])

    handle_successful_payment(
        authority=successful_payment.authority_id,
        ref_id="123",
        response={},
        session=DummySession(),
    )

    coupon.refresh_from_db()

    assert coupon.used_count == 1