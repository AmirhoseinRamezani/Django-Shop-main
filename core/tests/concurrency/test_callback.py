from unittest.mock import patch

import pytest

from payment.models import PaymentAttempt
from order.events.order_event import OrderEventType
from order.services.confirm_payment import confirm_order_payment
from django.core.exceptions import ValidationError
from django.db import close_old_connections
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


def test_late_callback_cannot_resurrect_old_attempt_after_retry():
    """A callback already in-flight must not finalize an attempt superseded by retry."""
    import threading

    from django.db import close_old_connections, transaction

    from payment.exceptions import PaymentInvariantViolation
    from payment.providers.base import GatewayPaymentResult
    from payment.repositories.payment_attempt_repository import (
        PaymentAttemptRepository,
    )
    from payment.services.retry import RetryPaymentService

    payment = PaymentFactory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        retry_count=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-OLD-CALLBACK-RACE",
    )

    gateway_entered = threading.Event()
    release_gateway = threading.Event()
    callback_errors = []

    verification_result = GatewayVerificationResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-OLD-CALLBACK-RACE",
        gateway_transaction_id="TX-OLD-CALLBACK-RACE",
        response_code="100",
        message="verified",
        amount=payment.amount,
        currency=payment.currency,
    )

    def verify_gateway(*args, **kwargs):
        gateway_entered.set()
        assert release_gateway.wait(timeout=10)
        return verification_result

    def callback_worker():
        close_old_connections()
        try:
            verify_callback(
                callback=GatewayCallback(
                    gateway=PaymentGateway.ZARINPAL,
                    authority=attempt.authority_id,
                )
            )
        except BaseException as exc:
            callback_errors.append(exc)
        finally:
            close_old_connections()

    thread = threading.Thread(target=callback_worker)

    with patch(
        "payment.services.verify.GatewayService.verify",
        side_effect=verify_gateway,
    ), patch(
        "payment.services.retry.GatewayService.initiate_payment",
        return_value=GatewayPaymentResult(
            success=True,
            gateway=PaymentGateway.ZARINPAL,
            authority="AUTH-NEW-RETRY",
            message="initiated",
            response_code="100",
        ),
    ), patch(
        "payment.services.retry.GatewayService.payment_url",
        return_value="https://gateway.test/AUTH-NEW-RETRY",
    ):
        thread.start()
        assert gateway_entered.wait(timeout=10)

        with transaction.atomic():
            locked_attempt = PaymentAttemptRepository.find_for_update(attempt.pk)
            locked_attempt.mark_failed(
                reason="Superseded by retry while verification was in flight.",
                response_code="-1",
                gateway_message="superseded",
            )
            PaymentAttemptRepository.save_failure(locked_attempt)

        RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/verify/",
        )

        release_gateway.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert len(callback_errors) == 1
    assert isinstance(callback_errors[0], PaymentInvariantViolation)

    payment.refresh_from_db()
    old_attempt = PaymentAttempt.objects.get(pk=attempt.pk)
    new_attempt = PaymentAttempt.objects.get(
        payment=payment,
        attempt_number=2,
    )

    assert payment.status == PaymentStatusType.PENDING
    assert old_attempt.status == PaymentAttemptStatus.FAILED
    assert new_attempt.status == PaymentAttemptStatus.PENDING
    assert new_attempt.authority_id == "AUTH-NEW-RETRY"

def test_confirm_while_callback_is_inside_provider_http():
    import threading

    payment = PaymentFactory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-CALLBACK-CONFIRM-RACE",
    )

    gateway_entered = threading.Event()
    release_gateway = threading.Event()
    errors = []

    result = GatewayVerificationResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-CALLBACK-CONFIRM-RACE",
        gateway_transaction_id="TX-CALLBACK-CONFIRM-RACE",
        response_code="100",
        message="verified",
        amount=payment.amount,
        currency=payment.currency,
    )

    def verify_gateway(*args, **kwargs):
        gateway_entered.set()
        assert release_gateway.wait(timeout=10)
        return result

    def callback_worker():
        close_old_connections()
        try:
            verify_callback(
                callback=GatewayCallback(
                    gateway=PaymentGateway.ZARINPAL,
                    authority=attempt.authority_id,
                )
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    with patch(
        "payment.services.verify.GatewayService.verify",
        side_effect=verify_gateway,
    ):
        thread = threading.Thread(target=callback_worker)
        thread.start()

        assert gateway_entered.wait(timeout=10)

        with pytest.raises(
            ValidationError,
            match="No successful payment found",
        ):
            confirm_order_payment(payment.order_id)

        release_gateway.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert errors == []

    payment.refresh_from_db()
    attempt.refresh_from_db()
    payment.order.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert attempt.payment_id == payment.pk
    assert payment.order.status == OrderStatusType.paid
    assert payment.order.events.filter(
        type=OrderEventType.PAID,
    ).count() == 1


def test_callback_success_then_confirm_is_idempotent():
    payment = PaymentFactory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-CALLBACK-CONFIRM-IDEMPOTENT",
    )

    result = GatewayVerificationResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-CALLBACK-CONFIRM-IDEMPOTENT",
        gateway_transaction_id="TX-CALLBACK-CONFIRM-IDEMPOTENT",
        response_code="100",
        message="verified",
        amount=payment.amount,
        currency=payment.currency,
    )

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=result,
    ):
        returned_payment = verify_callback(
            callback=GatewayCallback(
                gateway=PaymentGateway.ZARINPAL,
                authority=attempt.authority_id,
            )
        )

    payment.refresh_from_db()
    attempt.refresh_from_db()
    payment.order.refresh_from_db()

    assert returned_payment.pk == payment.pk
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert payment.order.status == OrderStatusType.paid

    paid_events_before = payment.order.events.filter(
        type=OrderEventType.PAID,
    ).count()

    confirmed_order = confirm_order_payment(payment.order_id)

    confirmed_order.refresh_from_db()

    assert confirmed_order.status == OrderStatusType.paid
    assert payment.is_consumed is True
    assert confirmed_order.events.filter(
        type=OrderEventType.PAID,
    ).count() == paid_events_before == 1

