# tests/concurrency/test_cancel_verify.py
from __future__ import annotations

import threading
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections

from order.models import (
    CouponReservation,
    CouponReservationReconciliation,
    CouponReservationStatus,
    CouponReconciliationOperation,
    CouponReconciliationStatus,
    OrderStatusType,
)
from order.services.coupon import CouponService
from order.services.state_machine import OrderStateMachine
from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType
from payment.exceptions import PaymentInvariantViolation
from payment.models import (
    PaymentResolution,
    PaymentResolutionReason,
    PaymentResolutionStatus,
)
from payment.providers.base import GatewayVerificationResult
from payment.services.verify import verify_payment
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory
from tests.factories.shop import CouponFactory


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
    Explicit cancellation may win, while expiry must defer if provider I/O is
    unresolved. A later positive result is durable but must not resurrect a
    terminal Order or consume the Payment without canonical finalization.
    """
    coupon = CouponFactory(max_limit_usage=1)
    order = OrderFactory(
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    CouponService.reserve_for_order(order)
    payment = PaymentFactory(order=order)
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
    worker_results = []
    reference = f"REF-CANCEL-VERIFY-{cancel_reason}"

    def gateway_verify(*args, **kwargs):
        gateway_entered.set()
        if not release_gateway.wait(timeout=10):
            raise AssertionError("test did not release the gateway barrier")
        return _successful_result(payment, reference=reference)

    def verification_worker():
        close_old_connections()
        try:
            result = verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
                ref_id=reference,
            )
            worker_results.append(result)
        except BaseException as exc:
            worker_errors.append(exc)
        finally:
            connections.close_all()

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
            if cancel_reason == "timeout":
                order.expire_at = timezone.now() - timedelta(seconds=1)
                order.save(update_fields=("expire_at",))
                call_command("expire_pending_orders")
            else:
                OrderStateMachine.transition(
                    order=order,
                    to_status=OrderStatusType.cancelled,
                    payload={"reason": cancel_reason},
                )
        finally:
            release_gateway.set()
            worker.join(timeout=15)

    assert not worker.is_alive(), "verification worker did not finish"
    # A recognized terminal-order conflict is now tracked as a durable
    # PaymentResolution. It is not returned as an exception to the callback
    # caller, while the successful Payment remains unconsumed.
    assert worker_errors == []
    assert len(worker_results) == 1
    assert worker_results[0].pk == payment.pk

    payment.refresh_from_db()
    attempt.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert attempt.gateway_reference == reference
    expected_order_status = (
        OrderStatusType.pending
        if cancel_reason == "timeout"
        else OrderStatusType.cancelled
    )
    assert order.status == expected_order_status
    coupon.refresh_from_db()
    coupon_reservation = CouponReservation.objects.get(order=order)
    assert coupon.reserved_count == 1
    assert coupon.used_count == 0
    assert coupon_reservation.status == CouponReservationStatus.RESERVED

    resolution = PaymentResolution.objects.get(payment=payment)
    expected_reason = (
        PaymentResolutionReason.ORDER_DEADLINE_PASSED
        if cancel_reason == "timeout"
        else PaymentResolutionReason.ORDER_CANCELLED
    )
    assert resolution.reason == expected_reason
    assert resolution.status == PaymentResolutionStatus.OPEN
    assert resolution.attempt_id == attempt.pk
    coupon_reconciliation = CouponReservationReconciliation.objects.get(order=order)
    assert coupon_reconciliation.status == CouponReconciliationStatus.RETRY
    assert coupon_reconciliation.expected_operation == CouponReconciliationOperation.REVIEW
    assert coupon_reconciliation.payment_id == payment.pk
    assert coupon_reconciliation.attempt_id == attempt.pk


def test_successful_verification_makes_later_cancellation_fail_closed():
    """If payment finalization wins, a later cancellation cannot undo it."""
    coupon = CouponFactory(max_limit_usage=1)
    order = OrderFactory(
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    CouponService.reserve_for_order(order)
    payment = PaymentFactory(order=order)
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
    coupon.refresh_from_db()
    coupon_reservation = CouponReservation.objects.get(order=order)
    assert coupon.used_count == 1
    assert coupon.reserved_count == 0
    assert coupon_reservation.status == CouponReservationStatus.CONSUMED

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
    A duplicate callback after cancellation is idempotent and auditable.

    The gateway's SUCCESS remains durable, the terminal Order is not
    resurrected, and an open Resolution records the unresolved discrepancy.
    """
    coupon = CouponFactory(max_limit_usage=1)
    order = OrderFactory(
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    CouponService.reserve_for_order(order)
    payment = PaymentFactory(order=order)
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
        first_result = verify_payment(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id=reference,
        )

    assert first_result.pk == payment.pk

    payment.refresh_from_db()
    attempt.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert order.status == OrderStatusType.cancelled
    coupon.refresh_from_db()
    coupon_reservation = CouponReservation.objects.get(order=order)
    assert coupon.reserved_count == 1
    assert coupon.used_count == 0
    assert coupon_reservation.status == CouponReservationStatus.RESERVED

    resolution = PaymentResolution.objects.get(payment=payment)
    assert resolution.status == PaymentResolutionStatus.OPEN
    assert resolution.reason == PaymentResolutionReason.ORDER_CANCELLED
    resolution_id = resolution.pk

    # A replay may return the already-verified Payment, but must preserve the
    # same durable Resolution and must not consume the Payment or repeat Order
    # side effects. This is idempotent recovery, not silent finalization.
    replay_result = verify_payment(
        payment_id=payment.pk,
        attempt_id=attempt.pk,
        ref_id=reference,
    )
    assert replay_result.pk == payment.pk

    payment.refresh_from_db()
    order.refresh_from_db()
    resolution.refresh_from_db()
    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is False
    assert order.status == OrderStatusType.cancelled
    coupon.refresh_from_db()
    coupon_reservation.refresh_from_db()
    assert coupon.reserved_count == 1
    assert coupon_reservation.status == CouponReservationStatus.RESERVED
    assert resolution.pk == resolution_id
    assert resolution.status == PaymentResolutionStatus.OPEN
    assert PaymentResolution.objects.filter(payment=payment).count() == 1


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
        PaymentInvariantViolation,
        match="Consumed Payment lacks matching canonical PAID event evidence",
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
