import pytest
from unittest.mock import patch

from tests.concurrency.base import ConcurrentRunner
from tests.factories.payment import PaymentAttemptFactory

from payment.enums import PaymentAttemptStatus, PaymentGateway
from payment.providers.base import GatewayVerificationResult
from payment.services.verify import verify_payment

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_verification_has_one_financial_effect(
    payment_factory,
):
    payment = payment_factory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-CONCURRENT",
    )

    result = GatewayVerificationResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-CONCURRENT",
        gateway_transaction_id="TXN-CONCURRENT",
        response_code="100",
        message="verified",
        amount=payment.amount,
        currency=payment.currency,
    )

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=result,
    ):
        runner = ConcurrentRunner()

        runner.run(
            lambda: verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
                ref_id="REF-CONCURRENT",
            ),
            lambda: verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
                ref_id="REF-CONCURRENT",
            ),
        )

    assert runner.errors == []

    payment.refresh_from_db()
    attempt.refresh_from_db()

    assert payment.is_successful
    assert payment.is_consumed
    assert attempt.status == PaymentAttemptStatus.SUCCESS
