from __future__ import annotations

import threading
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


pytestmark = pytest.mark.django_db(transaction=True)


def _successful_result(payment, *, reference: str) -> GatewayVerificationResult:
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


@pytest.mark.parametrize(
    "cancel_reason",
    [
        "customer-cancel",
        "timeout",
    ],
)
def test_cancel_or_expire_wins_while_gateway_verification_is_in_flight(
    cancel_reason,
):
    """
    The Order may be cancelled/expired while provider I/O is in flight.

    A later positive gateway response is still recorded as financial SUCCESS,
    but it must not resurrect the terminal Order or consume the Payment.
    """
    payment = PaymentFactory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id=f"AUTH-CANCEL-VERIFY-{cancel_reason}",
    )
    order = payment.order
    gateway_entered = threading.Event()
    release_gateway = threading.Event()
    worker_errors: list[BaseException] = []
    reference = f"REF-CANCEL-VERIFY-{cancel_reason}"

    def gateway_verify(*args, **kwargs):
        gateway_entered.set()
        if not release_gateway.wait(timeout=10):
            raise AssertionError("test did not release the gateway barrier")
        return _successful_result(payment, reference=reference)

    def verification_worker():
        close_old_connections()
        try:
            verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
                ref_id=reference,
            )
        except BaseException as exc:
            worker_errors.append(exc)
        finally:
            close_old_connections()

    worker = threading.Thread(target=verification_worker)
    with patch(
        "payment.services.verify.GatewayService.verify",
        side_effect=gateway_verify,
    ):
        worker.start()
        assert gateway_entered.wait(timeout=10), (
            "verification did not reach the gateway barrier"
        )
        try:
            OrderStateMachine.transition(
                order=order,
                to_status=OrderStatusType.cancelled,
                payload={"reason": cancel_reason},
            )
        finally:
            release_gateway.set()
            worker.join(timeout=15)

    assert not worker.is_alive(), "verification worker did not finish"
    assert len(worker_errors) == 1
    assert isinstance(worker_errors[0], ValidationError)

    payment.refresh_from_db()
    attempt.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert attempt.gateway_reference == reference
    assert order.status == OrderStatusType.cancelled


def test_successful_verification_makes_later_cancellation_fail_closed():
    """If payment finalization wins, a later cancellation cannot undo it."""
    payment = PaymentFactory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-VERIFY-WINS",
    )
    reference = "REF-VERIFY-WINS"

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=_successful_result(payment, reference=reference),
    ):
        verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id=reference,
        )

    payment.refresh_from_db()
    attempt.refresh_from_db()
    order = payment.order
    order.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert order.status == OrderStatusType.paid

    with pytest.raises(ValidationError, match="Illegal transition"):
        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
            payload={"reason": "late-cancel-after-payment"},
        )

    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.status == OrderStatusType.paid
    assert payment.is_consumed is True


def test_replay_after_cancelled_order_does_not_consume_successful_payment():
    """
    A duplicate callback after cancellation must not hide the discrepancy.

    The gateway's SUCCESS remains durable, while Order finalization fails
    closed and leaves the Payment unconsumed for reconciliation.
    """
    payment = PaymentFactory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-REPLAY-AFTER-CANCEL",
    )
    order = payment.order
    reference = "REF-REPLAY-AFTER-CANCEL"

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.cancelled,
        payload={"reason": "customer-cancel"},
    )

    with patch(
        "payment.services.verify.GatewayService.verify",
        return_value=_successful_result(payment, reference=reference),
    ):
        with pytest.raises(ValidationError):
            verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
                ref_id=reference,
            )

    payment.refresh_from_db()
    attempt.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert order.status == OrderStatusType.cancelled

    # The replay must validate the same Payment/Order binding and must not
    # silently return success merely because the Payment is already SUCCESS.
    with pytest.raises(ValidationError):
        verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id=reference,
        )

    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert order.status == OrderStatusType.cancelled


def test_consumed_successful_payment_with_pending_order_fails_closed():
    """A consumed Payment without its matching PAID Order event is an invariant failure."""
    payment = PaymentFactory(
        status=PaymentStatusType.SUCCESS,
        is_consumed=True,
    )
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        success=True,
        authority_id="AUTH-CONSUMED-INCONSISTENT",
        gateway_reference="REF-CONSUMED-INCONSISTENT",
        gateway_transaction_id="TX-CONSUMED-INCONSISTENT",
    )

    with pytest.raises(
        ValidationError,
        match="Consumed Payment is inconsistent with Order state or PAID event",
    ):
        verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id=attempt.gateway_reference,
        )

    payment.refresh_from_db()
    payment.order.refresh_from_db()
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert payment.order.status == OrderStatusType.pending
