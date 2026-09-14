# tests/e2e/test_payment.py
import pytest

from payment.enums import PaymentGateway
from payment.providers.base import GatewayPaymentResult, GatewayVerificationResult
from payment.services.services import PaymentService
from payment.services.verify import verify_payment

from tests.assertions import (
    refresh,
    assert_payment_success,
)

pytestmark = pytest.mark.django_db


class TestPaymentLifecycle:

    def test_payment_success(
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
                authority="AUTH123",
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
                gateway_reference="REF-AUTH123",
                gateway_transaction_id="TXN-AUTH123",
                response_code="100",
                message="verified",
                amount=payment.amount,
                currency=payment.currency,
            ),
        )

        verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id="REF-AUTH123",
            response={},
        )

        refresh(payment)

        assert_payment_success(payment)