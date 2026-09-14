import pytest

from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType
from payment.exceptions import PaymentGatewayError, PaymentInvariantViolation
from payment.models import PaymentAttempt
from payment.providers.base import GatewayPaymentResult
from payment.services.retry import RetryPaymentService

from tests.factories.payment import PaymentAttemptFactory


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
