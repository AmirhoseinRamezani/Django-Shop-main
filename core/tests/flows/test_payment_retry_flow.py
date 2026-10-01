import pytest

from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType
from payment.exceptions import (
    PaymentAlreadyProcessedError,
    PaymentGatewayError,
    PaymentIdempotencyConflictError,
    PaymentInvariantViolation,
)
from payment.models import PaymentAttempt
from payment.providers.base import GatewayPaymentResult
from payment.services.retry import RetryPaymentService

from tests.factories.payment import PaymentAttemptFactory, PaymentFactory


pytestmark = pytest.mark.django_db


def failed_attempt(payment, *, number=1):
    return PaymentAttemptFactory(
        payment=payment,
        attempt_number=number,
        retry_count=number,
        status=PaymentAttemptStatus.FAILED,
        failure_reason="Gateway rejected",
    )


def gateway_result(*, success=True, authority="AUTH-2", message=""):
    return GatewayPaymentResult(
        success=success,
        gateway=PaymentGateway.ZARINPAL,
        authority=authority if success else None,
        message=message,
        response_code="100" if success else "-1",
    )


def test_retry_uses_same_payment_and_creates_new_attempt(payment, mocker):
    first_attempt = failed_attempt(payment)
    payment_count = PaymentAttempt.objects.filter(payment=payment).values("payment").distinct().count()

    mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=gateway_result(),
    )
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-2",
    )

    payment_count_before = payment.__class__.objects.count()
    url = RetryPaymentService.retry(
        order=payment.order,
        callback_url="https://shop.test/payment/verify/",
    )

    attempts = PaymentAttempt.objects.filter(payment=payment).order_by("attempt_number")
    retry_attempt = attempts.get(attempt_number=2)
    payment.refresh_from_db()

    assert payment.__class__.objects.count() == payment_count_before
    assert attempts.count() == 2
    assert payment_count == 1
    assert retry_attempt.payment_id == payment.pk
    assert retry_attempt.retry_of_id == first_attempt.pk
    assert retry_attempt.retry_count == 2
    assert retry_attempt.status == PaymentAttemptStatus.PENDING
    assert retry_attempt.authority_id == "AUTH-2"
    assert payment.status == PaymentStatusType.PENDING
    assert url == "https://gateway.test/AUTH-2"


def test_retry_preserves_financial_snapshot(payment, mocker):
    failed_attempt(payment)
    snapshot = (payment.amount, payment.currency, payment.gateway, payment.order_id)

    mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=gateway_result(),
    )
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-2",
    )

    RetryPaymentService.retry(
        order=payment.order,
        callback_url="https://shop.test/payment/verify/",
    )

    payment.refresh_from_db()
    assert (payment.amount, payment.currency, payment.gateway, payment.order_id) == snapshot


def test_pending_attempt_with_authority_is_idempotent(payment, mocker):
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        retry_count=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-PENDING",
    )

    initiate = mocker.patch("payment.services.retry.GatewayService.initiate_payment")
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-PENDING",
    )

    url = RetryPaymentService.retry(
        order=payment.order,
        callback_url="https://shop.test/payment/verify/",
    )

    assert url == "https://gateway.test/AUTH-PENDING"
    initiate.assert_not_called()
    assert PaymentAttempt.objects.filter(payment=payment).count() == 1
    assert PaymentAttempt.objects.get(pk=attempt.pk).status == PaymentAttemptStatus.PENDING


def test_pending_attempt_without_authority_is_not_reinitiated(payment, mocker):
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        retry_count=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="",
    )
    initiate = mocker.patch("payment.services.retry.GatewayService.initiate_payment")

    with pytest.raises(PaymentGatewayError) as exc_info:
        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
        )

    assert exc_info.value.retryable is True
    initiate.assert_not_called()
    assert PaymentAttempt.objects.filter(payment=payment).count() == 1


def test_definitive_gateway_rejection_fails_attempt_not_payment(payment, mocker):
    first_attempt = failed_attempt(payment)
    mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=gateway_result(success=False, message="Rejected"),
    )

    with pytest.raises(PaymentGatewayError) as exc_info:
        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
        )

    retry_attempt = PaymentAttempt.objects.get(payment=payment, attempt_number=2)
    payment.refresh_from_db()

    assert retry_attempt.retry_of_id == first_attempt.pk
    assert retry_attempt.status == PaymentAttemptStatus.FAILED
    assert payment.status == PaymentStatusType.PENDING
    assert exc_info.value.retryable is False


def test_transport_failure_leaves_new_attempt_pending(payment, mocker):
    failed_attempt(payment)
    mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        side_effect=PaymentGatewayError("Gateway unavailable", retryable=True),
    )

    with pytest.raises(PaymentGatewayError) as exc_info:
        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
        )

    retry_attempt = PaymentAttempt.objects.get(payment=payment, attempt_number=2)
    payment.refresh_from_db()

    assert retry_attempt.status == PaymentAttemptStatus.PENDING
    assert payment.status == PaymentStatusType.PENDING
    assert exc_info.value.retryable is True


@pytest.mark.parametrize("status", [PaymentStatusType.SUCCESS, PaymentStatusType.FAILED])
def test_terminal_payment_cannot_retry(payment, status):
    payment.status = status
    payment.save(update_fields=["status"])

    with pytest.raises(Exception):
        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
        )


def test_retry_requires_previous_attempt(payment):
    with pytest.raises(PaymentInvariantViolation):
        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
        )


def test_retry_accepts_timeout_as_a_new_execution_cycle(payment, mocker):
    previous_attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        retry_count=1,
        status=PaymentAttemptStatus.TIMEOUT,
        failure_reason="Gateway timeout",
    )

    mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=gateway_result(),
    )
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-2",
    )

    url = RetryPaymentService.retry(
        order=payment.order,
        callback_url="https://shop.test/payment/verify/",
        idempotency_key="retry-timeout-1",
    )

    retry_attempt = PaymentAttempt.objects.get(
        payment=payment,
        attempt_number=2,
    )

    assert url == "https://gateway.test/AUTH-2"
    assert retry_attempt.retry_of_id == previous_attempt.pk
    assert retry_attempt.status == PaymentAttemptStatus.PENDING
    assert retry_attempt.retry_idempotency_key == "retry-timeout-1"


def test_retry_accepts_cancelled_as_a_new_execution_cycle(payment, mocker):
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        retry_count=1,
        status=PaymentAttemptStatus.CANCELLED,
        failure_reason="Cancelled by customer",
    )

    mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=gateway_result(),
    )
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-2",
    )

    RetryPaymentService.retry(
        order=payment.order,
        callback_url="https://shop.test/payment/verify/",
        idempotency_key="retry-cancelled-1",
    )

    retry_attempt = PaymentAttempt.objects.get(
        payment=payment,
        attempt_number=2,
    )

    assert retry_attempt.retry_idempotency_key == "retry-cancelled-1"
    assert retry_attempt.status == PaymentAttemptStatus.PENDING


def test_retry_same_idempotency_key_reuses_existing_attempt(payment, mocker):
    failed_attempt(payment)

    initiate = mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=gateway_result(),
    )
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-2",
    )

    first_url = RetryPaymentService.retry(
        order=payment.order,
        callback_url="https://shop.test/payment/verify/",
        idempotency_key="retry-idempotent-1",
    )
    second_url = RetryPaymentService.retry(
        order=payment.order,
        callback_url="https://shop.test/payment/verify/",
        idempotency_key="retry-idempotent-1",
    )

    assert first_url == second_url
    assert initiate.call_count == 1
    assert PaymentAttempt.objects.filter(payment=payment).count() == 2


def test_retry_rejects_different_idempotency_key_while_retry_is_pending(
    payment,
    mocker,
):
    failed_attempt(payment)

    initiate = mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=gateway_result(),
    )
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-2",
    )

    RetryPaymentService.retry(
        order=payment.order,
        callback_url="https://shop.test/payment/verify/",
        idempotency_key="retry-idempotent-a",
    )

    with pytest.raises(PaymentIdempotencyConflictError):
        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
            idempotency_key="retry-idempotent-b",
        )

    assert initiate.call_count == 1
    assert PaymentAttempt.objects.filter(payment=payment).count() == 2


def test_retry_idempotency_key_is_preserved_when_gateway_transport_fails(
    payment,
    mocker,
):
    failed_attempt(payment)

    mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        side_effect=PaymentGatewayError(
            "Gateway unavailable",
            retryable=True,
        ),
    )

    with pytest.raises(PaymentGatewayError):
        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
            idempotency_key="retry-unknown-1",
        )

    attempt = PaymentAttempt.objects.get(
        payment=payment,
        attempt_number=2,
    )

    assert attempt.status == PaymentAttemptStatus.PENDING
    assert attempt.retry_idempotency_key == "retry-unknown-1"


def test_retry_same_key_after_terminal_attempt_does_not_create_new_attempt(
    payment,
    mocker,
):
    failed_attempt(payment)

    mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=gateway_result(success=False, message="Rejected"),
    )

    with pytest.raises(PaymentGatewayError):
        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
            idempotency_key="retry-terminal-1",
        )

    initiate = mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
    )

    with pytest.raises(PaymentAlreadyProcessedError):
        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
            idempotency_key="retry-terminal-1",
        )

    initiate.assert_not_called()
    assert PaymentAttempt.objects.filter(payment=payment).count() == 2


def test_retry_rejects_key_longer_than_128_characters(payment):
    failed_attempt(payment)

    with pytest.raises(PaymentIdempotencyConflictError):
        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
            idempotency_key="x" * 129,
        )

    assert PaymentAttempt.objects.filter(payment=payment).count() == 1


def test_retry_idempotency_key_is_scoped_as_a_global_operation_identity(
    payment,
    mocker,
):
    failed_attempt(payment)

    mocker.patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=gateway_result(),
    )
    mocker.patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-2",
    )

    RetryPaymentService.retry(
        order=payment.order,
        callback_url="https://shop.test/payment/verify/",
        idempotency_key="global-retry-key",
    )

    other_payment = PaymentFactory()
    failed_attempt(other_payment)

    with pytest.raises(PaymentIdempotencyConflictError):
        RetryPaymentService.retry(
            order=other_payment.order,
            callback_url="https://shop.test/payment/verify/",
            idempotency_key="global-retry-key",
        )

    assert PaymentAttempt.objects.filter(payment=other_payment).count() == 1
