# tests/e2e/test_coupon_flow.py
import pytest

from order.services.coupon import CouponService
from order.services.inventory import InventoryService

from payment.enums import PaymentAttemptStatus, PaymentStatusType
from payment.services.payment_flow import handle_successful_payment

from tests.factories.payment import PaymentAttemptFactory

pytestmark = pytest.mark.django_db


class DummySession(dict):

    modified = False


def test_coupon_consumed_after_payment(
    order_with_coupon,
    payment_factory,
    coupon,
    django_capture_on_commit_callbacks,
):

    # Coupon snapshot must be persisted BEFORE any Payment row exists,
    # because the financial/coupon snapshot guard (TARGET-J1) freezes
    # coupon_code/coupon_discount_percent/coupon_id after the first
    # Payment creation.
    order = order_with_coupon
    CouponService.reserve_for_order(order)
    InventoryService.reserve(order)

    payment = payment_factory(
        order=order,
        status=PaymentStatusType.SUCCESS,
    )
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.SUCCESS,
        authority_id="AUTH-SUCCESSFUL",
        gateway_reference="REF-SUCCESSFUL",
        gateway_transaction_id="TXN-SUCCESSFUL",
        response_code="100",
        gateway_message="Payment successful",
    )

    with django_capture_on_commit_callbacks(execute=True):
        handle_successful_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id="REF-SUCCESSFUL",
            response={},
            session=DummySession(),
        )

    coupon.refresh_from_db()

    assert coupon.used_count == 1