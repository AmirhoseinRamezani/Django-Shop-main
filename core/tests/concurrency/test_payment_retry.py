from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections

from payment.enums import PaymentAttemptStatus, PaymentGateway
from payment.models import PaymentAttempt
from payment.providers.base import GatewayPaymentResult
from payment.services.retry import RetryPaymentService

from tests.factories.payment import PaymentAttemptFactory


pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_retries_create_at_most_one_new_attempt(payment, mocker):
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        retry_count=1,
        status=PaymentAttemptStatus.FAILED,
    )

    mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=GatewayPaymentResult(
            success=True,
            gateway=PaymentGateway.ZARINPAL,
            authority="AUTH-2",
        ),
    )
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-2",
    )

    def worker():
        close_old_connections()
        try:
            return RetryPaymentService.retry(
                order=payment.order,
                callback_url="https://shop.test/payment/verify/",
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: worker(), range(2)))

    attempts = list(
        PaymentAttempt.objects.filter(payment=payment).order_by("attempt_number")
    )

    assert len(attempts) == 2
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert attempts[1].retry_of_id == attempts[0].pk
    assert attempts[1].retry_count == 2
