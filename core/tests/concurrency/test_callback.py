from __future__ import annotations

import threading
from collections.abc import Callable

import pytest
from django.db import close_old_connections, connections

from order.events.order_event import OrderEventType
from order.models import OrderStatusType
from payment.enums import (
    PaymentAttemptStatus,
    PaymentGateway,
    PaymentStatusType,
)
from payment.exceptions import PaymentInvariantViolation
from payment.providers.base import GatewayCallback, GatewayVerificationResult
from payment.services.callback import verify_callback
from tests.factories.payment import PaymentAttemptFactory

pytestmark = pytest.mark.django_db(transaction=True)


_WORKER_JOIN_TIMEOUT = 20
_BARRIER_TIMEOUT = 10


def _run_concurrently(*targets: Callable[[], object]) -> list[BaseException]:
    """Run database workers on independent connections and collect failures."""
    if not targets:
        return []

    start = threading.Barrier(len(targets), timeout=_BARRIER_TIMEOUT)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def worker(target: Callable[[], object]) -> None:
        try:
            close_old_connections()
            start.wait()
            target()
        except BaseException as exc:  # propagate worker failures to pytest
            with errors_lock:
                errors.append(exc)
        finally:
            connections.close_all()

    threads = [
        threading.Thread(
            target=worker,
            args=(target,),
            name=f"callback-concurrency-{index}",
            daemon=True,
        )
        for index, target in enumerate(targets, start=1)
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(timeout=_WORKER_JOIN_TIMEOUT)

    alive = [thread.name for thread in threads if thread.is_alive()]
    if alive:
        raise AssertionError(
            "Concurrent callback workers did not terminate: "
            f"{', '.join(alive)}"
        )

    return errors


def _successful_gateway_result(
    payment,
    *,
    reference: str,
) -> GatewayVerificationResult:
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


def test_concurrent_duplicate_callbacks_have_one_financial_effect(
    payment_factory,
    monkeypatch,
):
    payment = payment_factory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-DUPLICATE-CALLBACK-RACE",
    )

    # Both callback requests must leave the snapshot transaction and reach the
    # provider boundary before either provider response is allowed to return.
    gateway_barrier = threading.Barrier(2, timeout=_BARRIER_TIMEOUT)
    gateway_calls: list[tuple[int, int, bool]] = []
    gateway_calls_lock = threading.Lock()
    results: list[int] = []
    results_lock = threading.Lock()

    gateway_result = _successful_gateway_result(
        payment,
        reference="REF-DUPLICATE-CALLBACK-RACE",
    )

    def verify_gateway(*, payment, attempt):
        from django.db import connection

        with gateway_calls_lock:
            gateway_calls.append(
                (payment.payment_id, attempt.attempt_id, connection.in_atomic_block)
            )

        gateway_barrier.wait()
        return gateway_result

    monkeypatch.setattr(
        "payment.services.verify.GatewayService.verify",
        verify_gateway,
    )

    callback = GatewayCallback(
        gateway=PaymentGateway.ZARINPAL,
        authority=attempt.authority_id,
        gateway_reference="REF-DUPLICATE-CALLBACK-RACE",
    )

    def verify() -> None:
        verified = verify_callback(callback=callback)
        with results_lock:
            results.append(verified.pk)

    errors = _run_concurrently(verify, verify)

    assert errors == []
    assert results == [payment.pk, payment.pk]
    assert len(gateway_calls) == 2
    assert all(
        payment_id == payment.pk
        and attempt_id == attempt.pk
        and not in_atomic
        for payment_id, attempt_id, in_atomic in gateway_calls
    )

    payment.refresh_from_db()
    attempt.refresh_from_db()
    order = payment.order
    order.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert order.status == OrderStatusType.paid

    paid_events = order.events.filter(type=OrderEventType.PAID)
    assert paid_events.count() == 1
    paid_event = paid_events.get()
    assert paid_event.payload["payment_id"] == payment.pk
    assert paid_event.payload["attempt_id"] == attempt.pk


def test_concurrent_callbacks_with_conflicting_gateway_references_fail_closed(
    payment_factory,
    monkeypatch,
):
    payment = payment_factory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-CONFLICTING-CALLBACK-RACE",
    )

    both_at_gateway = threading.Barrier(2, timeout=_BARRIER_TIMEOUT)
    first_response_returned = threading.Event()
    gateway_calls: list[tuple[int, int, bool]] = []
    gateway_calls_lock = threading.Lock()
    successful_results: list[int] = []
    rejected_results: list[BaseException] = []

    accepted_reference = "REF-CALLBACK-ACCEPTED"
    conflicting_reference = "REF-CALLBACK-CONFLICT"

    def verify_gateway(*, payment, attempt):
        from django.db import connection

        is_first = threading.current_thread().name.endswith("-1")
        with gateway_calls_lock:
            gateway_calls.append(
                (payment.payment_id, attempt.attempt_id, connection.in_atomic_block)
            )

        both_at_gateway.wait()

        if is_first:
            return _successful_gateway_result(
                payment,
                reference=accepted_reference,
            )

        # Ensure the first response has completed canonical persistence and
        # Order finalization before the conflicting response is reconciled.
        if not first_response_returned.wait(timeout=_BARRIER_TIMEOUT):
            raise AssertionError("first callback did not finish in time")

        return _successful_gateway_result(
            payment,
            reference=conflicting_reference,
        )

    monkeypatch.setattr(
        "payment.services.verify.GatewayService.verify",
        verify_gateway,
    )

    callback = GatewayCallback(
        gateway=PaymentGateway.ZARINPAL,
        authority=attempt.authority_id,
    )

    def accepted_callback() -> None:
        try:
            result = verify_callback(callback=callback)
            successful_results.append(result.pk)
        finally:
            first_response_returned.set()

    def conflicting_callback() -> None:
        try:
            verify_callback(callback=callback)
        except PaymentInvariantViolation as exc:
            rejected_results.append(exc)
        else:
            raise AssertionError(
                "A conflicting duplicate gateway reference was accepted."
            )

    errors = _run_concurrently(accepted_callback, conflicting_callback)

    assert errors == []
    assert successful_results == [payment.pk]
    assert len(rejected_results) == 1
    assert isinstance(rejected_results[0], PaymentInvariantViolation)
    assert len(gateway_calls) == 2
    assert all(
        payment_id == payment.pk
        and attempt_id == attempt.pk
        and not in_atomic
        for payment_id, attempt_id, in_atomic in gateway_calls
    )

    payment.refresh_from_db()
    attempt.refresh_from_db()
    order = payment.order
    order.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert attempt.gateway_reference == accepted_reference
    assert order.status == OrderStatusType.paid
    assert order.events.filter(type=OrderEventType.PAID).count() == 1


def test_historical_attempt_callback_never_falls_through_to_current_retry(
    payment_factory,
    monkeypatch,
):
    payment = payment_factory()
    historical_attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.TIMEOUT,
        authority_id="AUTH-HISTORICAL-CALLBACK",
    )
    current_attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=2,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-CURRENT-RETRY",
        retry_of=historical_attempt,
        retry_count=2,
    )

    monkeypatch.setattr(
        "payment.services.verify.GatewayService.verify",
        lambda **kwargs: pytest.fail(
            "A terminal historical attempt must not reach gateway verification."
        ),
    )

    with pytest.raises(PaymentInvariantViolation):
        verify_callback(
            callback=GatewayCallback(
                gateway=PaymentGateway.ZARINPAL,
                authority=historical_attempt.authority_id,
            ),
        )

    historical_attempt.refresh_from_db()
    current_attempt.refresh_from_db()
    payment.refresh_from_db()

    assert historical_attempt.status == PaymentAttemptStatus.TIMEOUT
    assert current_attempt.status == PaymentAttemptStatus.PENDING
    assert payment.status == PaymentStatusType.PENDING
