# tests/concurrency/test_coupon_race.py
from __future__ import annotations

import queue
import threading

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections

from order.events.order_event import OrderEventType
from order.models import OrderStatusType
from order.services.confirm_payment import confirm_order_payment
from order.services.coupon import CouponService
from payment.enums import PaymentAttemptStatus
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory
from tests.factories.shop import CouponFactory


pytestmark = pytest.mark.django_db(transaction=True)


def _build_paid_payment(order):
    payment = PaymentFactory(
        order=order,
        success=True,
    )
    attempt = PaymentAttemptFactory(
        payment=payment,
        success=True,
    )
    return payment, attempt


def _run_concurrently(*targets):
    outcomes: queue.Queue[tuple[int, object]] = queue.Queue()
    barrier = threading.Barrier(len(targets))

    def worker(index, target):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            outcomes.put((index, target()))
        except BaseException as exc:
            outcomes.put((index, exc))
        finally:
            connections.close_all()

    threads = [
        threading.Thread(
            target=worker,
            args=(index, target),
            name=f"coupon-finalization-{index}",
        )
        for index, target in enumerate(targets)
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(timeout=20)

    assert all(
        not thread.is_alive()
        for thread in threads
    ), "Concurrent worker did not terminate."

    results = dict(
        outcomes.get_nowait()
        for _ in threads
    )

    assert len(results) == len(threads)
    return results


def test_shared_single_use_coupon_is_consumed_exactly_once(
    monkeypatch,
):
    coupon = CouponFactory(
        max_limit_usage=1,
    )

    orders = [
        OrderFactory(
            coupon=coupon,
            coupon_code=coupon.code,
            coupon_discount_percent=coupon.discount_percent,
        )
        for _ in range(2)
    ]
    payments = [
        _build_paid_payment(order)
        for order in orders
    ]

    consume_barrier = threading.Barrier(2)
    original_consume = CouponService.consume

    def synchronized_consume(locked_coupon):
        consume_barrier.wait(timeout=10)
        return original_consume(locked_coupon)

    monkeypatch.setattr(
        CouponService,
        "consume",
        staticmethod(synchronized_consume),
    )

    results = _run_concurrently(
        lambda: confirm_order_payment(
            orders[0].pk,
            payments[0][0].pk,
        ),
        lambda: confirm_order_payment(
            orders[1].pk,
            payments[1][0].pk,
        ),
    )

    successes = [
        result
        for result in results.values()
        if not isinstance(result, BaseException)
    ]
    failures = [
        result
        for result in results.values()
        if isinstance(result, BaseException)
    ]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ValidationError)

    coupon.refresh_from_db()
    for order in orders:
        order.refresh_from_db()
    for payment, attempt in payments:
        payment.refresh_from_db()
        attempt.refresh_from_db()

    assert coupon.used_count == 1
    assert sum(
        order.status == OrderStatusType.paid
        for order in orders
    ) == 1
    assert sum(
        payment.is_consumed
        for payment, _ in payments
    ) == 1
    assert all(
        attempt.status == PaymentAttemptStatus.SUCCESS
        for _, attempt in payments
    )

    paid_events = [
        event
        for order in orders
        for event in order.events.filter(
            type=OrderEventType.PAID,
        )
    ]
    assert len(paid_events) == 1
    assert paid_events[0].payload["payment_id"] == next(
        payment.pk
        for payment, _ in payments
        if payment.is_consumed
    )


def test_repeated_confirmation_consumes_coupon_once():
    coupon = CouponFactory(
        max_limit_usage=1,
    )
    order = OrderFactory(
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    payment, attempt = _build_paid_payment(order)

    first_result = confirm_order_payment(
        order.pk,
        payment.pk,
    )
    second_result = confirm_order_payment(
        order.pk,
        payment.pk,
    )

    coupon.refresh_from_db()
    order.refresh_from_db()
    payment.refresh_from_db()
    attempt.refresh_from_db()

    assert first_result.status == OrderStatusType.paid
    assert second_result.status == OrderStatusType.paid
    assert order.status == OrderStatusType.paid
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert coupon.used_count == 1
    assert (
        order.events
        .filter(type=OrderEventType.PAID)
        .count()
        == 1
    )


def test_exhausted_coupon_rolls_back_payment_finalization():
    coupon = CouponFactory(
        max_limit_usage=1,
        used_count=1,
    )
    order = OrderFactory(
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    payment, attempt = _build_paid_payment(order)

    with pytest.raises(
        ValidationError,
        match="Coupon cannot be consumed",
    ):
        confirm_order_payment(
            order.pk,
            payment.pk,
        )

    coupon.refresh_from_db()
    order.refresh_from_db()
    payment.refresh_from_db()
    attempt.refresh_from_db()

    assert coupon.used_count == 1
    assert order.status == OrderStatusType.pending
    assert order.paid_date is None
    assert payment.is_consumed is False
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert (
        order.events
        .filter(type=OrderEventType.PAID)
        .count()
        == 0
    )