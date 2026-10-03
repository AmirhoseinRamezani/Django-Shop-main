# tests/concurrency/test_verify_confirm.py
from __future__ import annotations

from threading import Event, Thread
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction

from order.events.order_event import OrderEventType
from order.models import OrderStatusType
from order.services.confirm_payment import confirm_order_payment

from payment.enums import (
    PaymentAttemptStatus,
    PaymentGateway,
    PaymentStatusType,
)
from payment.exceptions import PaymentInvariantViolation
from payment.models import PaymentAttempt
from payment.providers.base import GatewayVerificationResult
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from payment.services.verify import verify_payment

from tests.concurrency.base import ConcurrentRunner
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory


pytestmark = pytest.mark.django_db(transaction=True)


def _verification_result(payment, *, reference="REF-VERIFY-CONFIRM"):
    return GatewayVerificationResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference=reference,
        gateway_transaction_id=f"TX-{reference}",
        response_code="100",
        message="verified",
        amount=payment.amount,
        currency=payment.currency,
    )


def _pending_payment():
    payment = PaymentFactory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        retry_count=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-VERIFY-CONFIRM",
    )
    return payment, attempt


def test_confirm_while_verify_is_inside_provider_http():
    payment, attempt = _pending_payment()
    gateway_entered = Event()
    release_gateway = Event()
    errors = []

    def verify_gateway(*args, **kwargs):
        gateway_entered.set()
        assert release_gateway.wait(timeout=10)
        return _verification_result(payment)

    def worker():
        close_old_connections()
        try:
            verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    with patch(
        "payment.services.verify.GatewayService.verify",
        side_effect=verify_gateway,
    ):
        thread = Thread(target=worker)
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


def test_provider_success_binds_exact_payment_attempt_and_pays_order():
    payment, attempt = _pending_payment()
    result = _verification_result(
        payment,
        reference="REF-EXACT-BINDING",
    )

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=result,
    ) as gateway:
        returned_payment = verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
        )

    payment.refresh_from_db()
    attempt.refresh_from_db()
    payment.order.refresh_from_db()

    assert returned_payment.pk == payment.pk
    assert gateway.call_count == 1
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert attempt.payment_id == payment.pk
    assert attempt.gateway_reference == result.gateway_reference
    assert attempt.gateway_transaction_id == result.gateway_transaction_id
    assert payment.order_id == payment.order.pk
    assert payment.order.status == OrderStatusType.paid
    assert payment.order.events.filter(
        type=OrderEventType.PAID,
    ).count() == 1


def test_concurrent_verify_x_verify_has_one_financial_effect():
    payment, attempt = _pending_payment()
    result = _verification_result(
        payment,
        reference="REF-CONCURRENT-VERIFY",
    )

    def worker():
        verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
        )

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=result,
    ) as gateway:
        ConcurrentRunner().run(worker, worker)

    payment.refresh_from_db()
    attempt.refresh_from_db()
    payment.order.refresh_from_db()

    assert gateway.call_count == 2
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert payment.order.status == OrderStatusType.paid
    assert payment.order.events.filter(
        type=OrderEventType.PAID,
    ).count() == 1


def test_stale_verify_cannot_authorize_newer_retry_attempt():
    payment, old_attempt = _pending_payment()
    gateway_entered = Event()
    release_gateway = Event()
    errors = []

    result = _verification_result(
        payment,
        reference="REF-OLD-VERIFY",
    )

    def verify_gateway(*args, **kwargs):
        gateway_entered.set()
        assert release_gateway.wait(timeout=10)
        return result

    def worker():
        close_old_connections()
        try:
            verify_payment(
                payment_id=payment.pk,
                attempt_id=old_attempt.pk,
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    with patch(
        "payment.services.verify.GatewayService.verify",
        side_effect=verify_gateway,
    ):
        thread = Thread(target=worker)
        thread.start()

        assert gateway_entered.wait(timeout=10)

        with transaction.atomic():
            locked_attempt = PaymentAttemptRepository.find_for_update(
                old_attempt.pk,
            )
            locked_attempt.mark_failed(
                reason="Superseded by newer retry.",
                response_code="-1",
                gateway_message="superseded",
            )
            PaymentAttemptRepository.save_failure(locked_attempt)

        new_attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            retry_count=2,
            retry_of=old_attempt,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-NEW-VERIFY",
        )

        release_gateway.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], PaymentInvariantViolation)

    payment.refresh_from_db()
    old_attempt.refresh_from_db()
    new_attempt.refresh_from_db()

    assert payment.status == PaymentStatusType.PENDING
    assert payment.is_consumed is False
    assert old_attempt.status == PaymentAttemptStatus.FAILED
    assert new_attempt.status == PaymentAttemptStatus.PENDING
    assert new_attempt.payment_id == payment.pk
    assert new_attempt.authority_id == "AUTH-NEW-VERIFY"
    assert payment.order.status != OrderStatusType.paid


def test_verify_success_then_confirm_is_idempotent():
    payment, attempt = _pending_payment()

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=_verification_result(
            payment,
            reference="REF-VERIFY-FIRST",
        ),
    ):
        returned_payment = verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
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

    payment.refresh_from_db()
    confirmed_order.refresh_from_db()

    assert confirmed_order.pk == payment.order_id
    assert confirmed_order.status == OrderStatusType.paid
    assert payment.is_consumed is True
    assert confirmed_order.events.filter(
        type=OrderEventType.PAID,
    ).count() == paid_events_before == 1


def test_payment_is_bound_to_exact_order():
    payment_a, attempt_a = _pending_payment()
    payment_b, attempt_b = _pending_payment()

    payment_a_order_id = payment_a.order_id
    payment_b_order_id = payment_b.order_id

    assert payment_a_order_id != payment_b_order_id

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=_verification_result(
            payment_a,
            reference="REF-ORDER-A",
        ),
    ):
        verify_payment(
            payment_id=payment_a.pk,
            attempt_id=attempt_a.pk,
        )

    payment_a.refresh_from_db()
    attempt_a.refresh_from_db()
    payment_b.refresh_from_db()
    attempt_b.refresh_from_db()
    payment_a.order.refresh_from_db()
    payment_b.order.refresh_from_db()

    assert payment_a.order_id == payment_a_order_id
    assert payment_b.order_id == payment_b_order_id
    assert payment_a.order.status == OrderStatusType.paid
    assert payment_b.order.status != OrderStatusType.paid
    assert payment_a.is_consumed is True
    assert payment_b.is_consumed is False

    with pytest.raises(
        ValidationError,
        match="No successful payment found",
    ):
        confirm_order_payment(payment_b_order_id)

    payment_b.refresh_from_db()
    payment_b.order.refresh_from_db()

    assert payment_b.is_consumed is False
    assert payment_b.order.status != OrderStatusType.paid
