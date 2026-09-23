from unittest.mock import patch

import pytest

from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType
from payment.providers.base import GatewayCallback, GatewayVerificationResult
from payment.services.callback import verify_callback
from order.models import OrderStatusType
from tests.concurrency.base import ConcurrentRunner
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory


pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_duplicate_callbacks_have_one_financial_effect():
    payment = PaymentFactory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-CONCURRENT-CALLBACK",
    )

    result = GatewayVerificationResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-CONCURRENT-CALLBACK",
        gateway_transaction_id="TX-CONCURRENT-CALLBACK",
        response_code="100",
        message="verified",
        amount=payment.amount,
        currency=payment.currency,
    )

    errors = []

    def callback():
        try:
            verify_callback(
                callback=GatewayCallback(
                    gateway=PaymentGateway.ZARINPAL,
                    authority=attempt.authority_id,
                )
            )
        except Exception as exc:
            errors.append(exc)

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=result,
    ) as gateway:
        ConcurrentRunner().run(callback, callback)

    payment.refresh_from_db()
    attempt.refresh_from_db()
    payment.order.refresh_from_db()

    assert errors == []
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert payment.order.status == OrderStatusType.paid
    assert gateway.call_count == 2
