# tests/e2e/test_coupon.py
import pytest

from order.services.coupon import CouponService

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
        django_capture_on_commit_callbacks,
    ):
        order = successful_payment.order

        order.coupon = coupon
        order.coupon_code = coupon.code
        order.coupon_discount_percent = coupon.discount_percent
        order.save(
            update_fields=["coupon", "coupon_code", "coupon_discount_percent"],
        )
        CouponService.reserve_for_order(order)

        with django_capture_on_commit_callbacks(execute=True):
            handle_successful_payment(
                payment_id=successful_payment.pk,
                attempt_id=successful_payment.attempts.get().pk,
                ref_id="REF-SUCCESSFUL",
                response={},
                session=DummySession(),
            )

        refresh(coupon)

        assert_coupon_used(coupon)