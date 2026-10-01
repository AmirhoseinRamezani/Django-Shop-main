# tests/e2e/test_customer_checkout.py
import pytest

from order.models import OrderStatusType
from payment.enums import PaymentGateway, PaymentStatusType
from payment.providers.base import GatewayPaymentResult, GatewayVerificationResult
from order.services.order import OrderService
from payment.services.services import PaymentService
from payment.services.payment_flow import handle_successful_payment


pytestmark = pytest.mark.django_db


class DummySession(dict):

    modified = False


class TestCustomerCheckout:

    def test_customer_checkout(
        self,
        user,
        address,
        cart_builder,
        product,
        mocker,
    ):
        cart = (
            cart_builder
            .with_user(user)
            .add(product=product, qty=2)
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
                authority="AUTH-100",
            ),
        )

        mocker.patch(
            "payment.services.services.GatewayService.payment_url",
            return_value="payment-url",
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
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
                gateway_reference="REF-AUTH-100",
                gateway_transaction_id="TXN-AUTH-100",
                response_code="100",
                message="verified",
                amount=payment.amount,
                currency=payment.currency,
            ),
        )

        handle_successful_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id="REF-AUTH-100",
            response={},
            session=DummySession(),
        )

        order.refresh_from_db()
        payment.refresh_from_db()

        assert order.status == OrderStatusType.paid
        assert payment.status == PaymentStatusType.SUCCESS
        assert payment.is_consumed
