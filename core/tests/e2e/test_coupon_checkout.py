# tests/e2e/test_coupon_checkout.py

import pytest

from payment.services.services import PaymentService
from payment.services.payment_flow import handle_successful_payment


pytestmark = pytest.mark.django_db


class DummySession(dict):

    modified = False


class TestCouponCheckout:

    def test_coupon_used_after_success_payment(
        self,
        user,
        address,
        coupon,
        cart_builder,
        product,
        mocker,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product)
            .build()
        )

        gateway = mocker.patch(
            "payment.services.services.ZarinPalSandbox"
        )

        gateway.return_value.payment_request.return_value = {
            "Authority": "AUTH-1",
        }

        gateway.return_value.generate_payment_url.return_value = "url"

        from order.services.order import OrderService

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
            coupon=coupon,
        )

        PaymentService.start_payment(order)

        payment = order.payments.get()

        handle_successful_payment(
            authority=payment.authority_id,
            ref_id="111",
            response={},
            session=DummySession(),
        )

        coupon.refresh_from_db()

        assert coupon.used_count == 1