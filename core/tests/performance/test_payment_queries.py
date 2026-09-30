# tests/performance/test_payment_queries.py
import pytest

from tests.helpers.queries import (
    assert_max_queries,
)

from payment.enums import PaymentAttemptStatus
from payment.providers.base import GatewayVerificationResult
from payment.services.verify import verify_payment
from tests.factories.payment import PaymentAttemptFactory


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.performance,
]


class TestVerifyQueries:

    def test_verify_payment_queries(
        self,
        payment,
        mocker,
    ):
        mocker.patch(
            "payment.services.verify._consume_successful_payment",
            return_value=payment,
        )
        attempt = PaymentAttemptFactory(
            payment=payment,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-PERF",
        )

        mocker.patch(
            "payment.services.verify.GatewayService.verify",
            return_value=GatewayVerificationResult(
                success=True,
                gateway=payment.gateway,
                gateway_reference="REF-PERF",
                gateway_transaction_id="TXN-PERF",
                response_code="100",
                message="verified",
                amount=payment.amount,
                currency=payment.currency,
            ),
        )

        attempt = payment.attempts.order_by(
            "-attempt_number",
            "-id",
        ).first()

        assert_max_queries(
            12,
            verify_payment,
            payment_id=payment.id,
            attempt_id=attempt.id,
            ref_id="REF-PERF",
            response={},
        )