# tests/integration/test_payment_flow.py
import pytest

from payment.enums import PaymentGateway
from payment.providers.base import GatewayPaymentResult, GatewayVerificationResult
from payment.services.services import PaymentService
from payment.services.payment_flow import (
    handle_successful_payment,
)

from tests.helpers.session import DummySession


pytestmark = pytest.mark.django_db


class TestPaymentFlow:

    def test_payment_flow(
        self,
        order,
        mocker,
    ):
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

        PaymentService.start_payment(
            order,
            callback_url="https://shop.test/payment/verify/",
        )

        payment = order.payments.first()
        attempt = payment.attempts.first()

        mocker.patch(
            "payment.services.verify.GatewayService.verify",
            return_value=GatewayVerificationResult(
                success=True,
                gateway=PaymentGateway.ZARINPAL,
                gateway_reference="REF-1",
                gateway_transaction_id="TXN-1",
                response_code="100",
                message="verified",
                amount=payment.amount,
                currency=payment.currency,
            ),
        )

        order = handle_successful_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id="REF-1",
            response={},
            session=DummySession(),
        )

        payment.refresh_from_db()

        assert payment.is_consumed

        assert order.pk == payment.order_id
