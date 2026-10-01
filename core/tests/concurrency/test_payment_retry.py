from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections

from payment.enums import PaymentAttemptStatus, PaymentGateway
from payment.exceptions import PaymentIdempotencyConflictError, PaymentGatewayError
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


def test_concurrent_same_retry_key_creates_one_attempt(payment, mocker):
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        retry_count=1,
        status=PaymentAttemptStatus.FAILED,
    )

    initiate = mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=GatewayPaymentResult(
            success=True,
            gateway=PaymentGateway.ZARINPAL,
            authority="AUTH-RETRY",
        ),
    )
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-RETRY",
    )

    def worker():
        close_old_connections()
        try:
            return RetryPaymentService.retry(
                order=payment.order,
                callback_url="https://shop.test/payment/verify/",
                idempotency_key="concurrent-retry-1",
            )
        except Exception as exc:
            return exc
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: worker(), range(2)))

    attempts = list(
        PaymentAttempt.objects.filter(payment=payment).order_by("attempt_number")
    )

    assert len(attempts) == 2
    assert attempts[1].retry_idempotency_key == "concurrent-retry-1"
    assert initiate.call_count == 1
    assert any(isinstance(result, str) for result in results) or any(
        isinstance(result, PaymentGatewayError) for result in results
    )


def test_concurrent_different_retry_keys_create_at_most_one_attempt(
    payment,
    mocker,
):
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
            authority="AUTH-RETRY",
        ),
    )
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-RETRY",
    )

    def worker(key):
        close_old_connections()
        try:
            return RetryPaymentService.retry(
                order=payment.order,
                callback_url="https://shop.test/payment/verify/",
                idempotency_key=key,
            )
        except Exception as exc:
            return exc
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                worker,
                ("concurrent-retry-a", "concurrent-retry-b"),
            )
        )

    attempts = list(
        PaymentAttempt.objects.filter(payment=payment).order_by("attempt_number")
    )

    assert len(attempts) == 2
    assert len({attempt.retry_idempotency_key for attempt in attempts[1:]}) == 1
    assert any(isinstance(result, PaymentIdempotencyConflictError) for result in results)
