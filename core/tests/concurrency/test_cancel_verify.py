from __future__ import annotations

from threading import Event, Thread
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections

from order.models import OrderStatusType
from order.services.state_machine import OrderStateMachine
from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType
from payment.providers.base import GatewayVerificationResult
from payment.services.verify import verify_payment
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory
from tests.factories.order import OrderFactory


pytestmark = pytest.mark.django_db(transaction=True)


def _pending_payment_for_order(order):
    payment = PaymentFactory(order=order)
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-CANCEL-VERIFY-RACE",
    )
    return payment, attempt


def _success_result(payment):
    return GatewayVerificationResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-CANCEL-VERIFY-RACE",
        gateway_transaction_id="TX-CANCEL-VERIFY-RACE",
        response_code="100",
        message="verified",
        amount=payment.amount,
        currency=payment.currency,
    )


def test_cancel_wins_while_verification_is_in_flight():
    order = OrderFactory()
    payment, attempt = _pending_payment_for_order(order)

    gateway_entered = Event()
    release_gateway = Event()
    verification_errors = []

    def verify_gateway(*args, **kwargs):
        gateway_entered.set()
        assert release_gateway.wait(timeout=10)
        return _success_result(payment)

    def verification_worker():
        try:
            verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
            )
        except BaseException as exc:
            verification_errors.append(exc)
        finally:
            close_old_connections()

    with patch(
        "payment.services.verify.GatewayService.verify",
        side_effect=verify_gateway,
    ):
        thread = Thread(target=verification_worker)
        thread.start()

        assert gateway_entered.wait(timeout=10)

        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
        )

        release_gateway.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert len(verification_errors) == 1
    assert isinstance(verification_errors[0], ValidationError)

    order.refresh_from_db()
    payment.refresh_from_db()
    attempt.refresh_from_db()

    assert order.status == OrderStatusType.cancelled
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert attempt.gateway_reference == "REF-CANCEL-VERIFY-RACE"
    assert attempt.gateway_transaction_id == "TX-CANCEL-VERIFY-RACE"


def test_verification_wins_then_cancellation_is_rejected():
    order = OrderFactory()
    payment, attempt = _pending_payment_for_order(order)

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=_success_result(payment),
    ):
        verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
        )

    with pytest.raises(ValidationError):
        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
        )

    order.refresh_from_db()
    payment.refresh_from_db()
    attempt.refresh_from_db()

    assert order.status == OrderStatusType.paid
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS


def test_duplicate_verification_after_cancellation_does_not_create_paid_order():
    order = OrderFactory()
    payment, attempt = _pending_payment_for_order(order)

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.cancelled,
    )

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=_success_result(payment),
    ):
        with pytest.raises(ValidationError):
            verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
            )

    order.refresh_from_db()
    payment.refresh_from_db()
    attempt.refresh_from_db()

    assert order.status == OrderStatusType.cancelled
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert attempt.status == PaymentAttemptStatus.SUCCESS
