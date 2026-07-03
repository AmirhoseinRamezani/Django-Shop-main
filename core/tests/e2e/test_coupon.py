# tests/e2e/test_coupon.py
import pytest

from payment.services.payment_flow import (
    handle_successful_payment,
)

from tests.assertions import (
    refresh,
    assert_coupon_used,
)

pytestmark = pytest.mark.django_db


class DummySession(dict):

    modified = False


class TestCouponFlow:

    def test_coupon_consumed_after_payment(
        self,
        successful_payment,
        coupon,
    ):
        order = successful_payment.order

        order.coupon = coupon

        order.save(
            update_fields=["coupon"],
        )

        handle_successful_payment(
            authority=successful_payment.authority_id,
            ref_id="123",
            response={},
            session=DummySession(),
        )

        refresh(coupon)

        assert_coupon_used(coupon)