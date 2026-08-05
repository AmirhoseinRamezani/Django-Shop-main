import pytest

from payment.services.payment_flow import (
    handle_successful_payment,
)

from tests.assertions import refresh

pytestmark = pytest.mark.django_db


class DummySession(dict):

    modified = False


class TestPaymentFlow:

    def test_returns_order(
        self,
        payment,
    ):
        session = DummySession()

        order = handle_successful_payment(
            authority=payment.authority_id,
            ref_id=111,
            response={},
            session=session,
        )

        refresh(payment)

        assert payment.is_consumed
        assert order.pk == payment.order_id

    def test_consumes_coupon(
        self,
        payment,
        mocker,
    ):
        session = DummySession()

        verify = mocker.patch(
            "payment.services.payment_flow.verify_payment"
        )

        verify.return_value = payment

        coupon = payment.order.coupon

        if coupon:
            coupon.mark_used = mocker.Mock()

        handle_successful_payment(
            authority="A",
            ref_id=111,
            response={},
            session=session,
        )

        if coupon:
            coupon.mark_used.assert_called_once()

    def test_clear_cart(
        self,
        payment,
        mocker,
    ):
        session = DummySession()

        verify = mocker.patch(
            "payment.services.payment_flow.verify_payment"
        )

        verify.return_value = payment

        clear = mocker.patch(
            "payment.services.payment_flow.CartSession.clear"
        )

        handle_successful_payment(
            authority="A",
            ref_id=1,
            response={},
            session=session,
        )

        clear.assert_called_once()