# tests/e2e/test_coupon_checkout.py

import pytest

from payment.enums import PaymentGateway
from payment.providers.base import GatewayPaymentResult, GatewayVerificationResult
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
            .with_user(user)
            .add(product=product)
            .build()
        )

        mocker.patch(
            "payment.services.services.GatewayService.current_gateway",
            return_value=PaymentGateway.ZARINPAL,
        )

        mocker.patch(
            "payment.services.services.GatewayService.initiate_payment",
            return_value=GatewayPaymentResult(
                success=True,
                gateway=PaymentGateway.ZARINPAL,
                authority="AUTH-1",
            ),
        )

        mocker.patch(
            "payment.services.services.GatewayService.payment_url",
            return_value="url",
        )

        from order.services.order import OrderService

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
            coupon=coupon,
        )

        PaymentService.start_payment(
        order,
        callback_url="https://shop.test/payment/verify/",
    )

        payment = order.payments.get()
        attempt = payment.attempts.get()

        mocker.patch(
            "payment.services.verify.GatewayService.verify",
            return_value=GatewayVerificationResult(
                success=True,
                gateway=PaymentGateway.ZARINPAL,
                gateway_reference="REF-AUTH-1",
                gateway_transaction_id="TXN-AUTH-1",
                response_code="100",
                message="verified",
                amount=payment.amount,
                currency=payment.currency,
            ),
        )

        handle_successful_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id="REF-AUTH-1",
            response={},
            session=DummySession(),
        )

        coupon.refresh_from_db()

        assert coupon.used_count == 1