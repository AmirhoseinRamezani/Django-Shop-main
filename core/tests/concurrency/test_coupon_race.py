# tests/concurrency/test_coupon_race.py
from __future__ import annotations

import pytest

from django.core.exceptions import ValidationError

from order.models import (
    CouponModel,
    OrderStatusType,
)
from order.services.confirm_payment import confirm_order_payment

from payment.enums import PaymentStatusType

from tests.concurrency.base import ConcurrentRunner
from tests.factories.order import OrderFactory
from tests.factories.payment import (
    PaymentAttemptFactory,
    PaymentFactory,
)
from tests.factories.shop import CouponFactory


pytestmark = pytest.mark.django_db(transaction=True)


def _create_successful_payment(order):
    payment = PaymentFactory(
        order=order,
        status=PaymentStatusType.SUCCESS,
    )

    PaymentAttemptFactory(
        payment=payment,
        success=True,
    )

    return payment


def test_coupon_capacity_is_exactly_once_under_concurrent_confirmation():
    """
    Two different Orders concurrently attempt to consume the same
    single-use coupon.

    Financial invariant:

        coupon.max_limit_usage == 1
        =>
        successful coupon consumptions <= 1

    The losing Order must remain pending and its Payment must remain
    unconsumed because CouponService.consume() participates in the same
    outer transaction as payment consumption and Order -> PAID.
    """

    coupon = CouponFactory(
        max_limit_usage=1,
        used_count=0,
        is_active=True,
    )

    order_a = OrderFactory(
        coupon=coupon,
        payable_price=100000,
        total_price=100000,
        subtotal_price=100000,
    )

    order_b = OrderFactory(
        coupon=coupon,
        payable_price=100000,
        total_price=100000,
        subtotal_price=100000,
    )

    payment_a = _create_successful_payment(order_a)
    payment_b = _create_successful_payment(order_b)

    results: list[str] = []

    def confirm(order_id: int):
        try:
            confirm_order_payment(order_id)
            results.append("success")
        except ValidationError:
            results.append("rejected")

    runner = ConcurrentRunner()

    runner.run(
        lambda: confirm(order_a.pk),
        lambda: confirm(order_b.pk),
    )

    assert runner.errors == []

    coupon.refresh_from_db()
    order_a.refresh_from_db()
    order_b.refresh_from_db()
    payment_a.refresh_from_db()
    payment_b.refresh_from_db()

    # Exactly one order may consume a single-use coupon.
    assert coupon.used_count == 1
    assert results.count("success") == 1
    assert results.count("rejected") == 1

    # Exactly one financial confirmation succeeded.
    assert (
        [order_a.status, order_b.status].count(
            OrderStatusType.paid,
        )
        == 1
    )

    assert (
        [order_a.status, order_b.status].count(
            OrderStatusType.pending,
        )
        == 1
    )

    # The successful Payment was consumed.
    assert (
        [payment_a.is_consumed, payment_b.is_consumed].count(True)
        == 1
    )

    # The rejected confirmation must have rolled back Payment consumption.
    assert (
        [payment_a.is_consumed, payment_b.is_consumed].count(False)
        == 1
    )


def test_repeated_confirmation_does_not_consume_coupon_twice():
    """
    Canonical confirmation is idempotent.

    Calling confirm_order_payment() twice for the same Order must not
    increment coupon usage twice.
    """

    coupon = CouponFactory(
        max_limit_usage=1,
        used_count=0,
        is_active=True,
    )

    order = OrderFactory(
        coupon=coupon,
        payable_price=100000,
        total_price=100000,
        subtotal_price=100000,
    )

    payment = _create_successful_payment(order)

    first = confirm_order_payment(order.pk)
    second = confirm_order_payment(order.pk)

    coupon.refresh_from_db()
    order.refresh_from_db()
    payment.refresh_from_db()

    assert first.pk == second.pk

    assert order.status == OrderStatusType.paid
    assert payment.is_consumed is True

    # Exactly one coupon usage despite two confirmation calls.
    assert coupon.used_count == 1


def test_coupon_exhaustion_rolls_back_second_order_confirmation():
    """
    A second Order must not become PAID when its shared coupon is already
    exhausted.

    The failed confirmation must leave both Order and Payment untouched.
    """

    coupon = CouponFactory(
        max_limit_usage=1,
        used_count=1,
        is_active=True,
    )

    order = OrderFactory(
        coupon=coupon,
        payable_price=100000,
        total_price=100000,
        subtotal_price=100000,
    )

    payment = _create_successful_payment(order)

    with pytest.raises(
        ValidationError,
        match="Coupon cannot be consumed",
    ):
        confirm_order_payment(order.pk)

    order.refresh_from_db()
    payment.refresh_from_db()
    coupon.refresh_from_db()

    assert order.status == OrderStatusType.pending
    assert payment.is_consumed is False
    assert coupon.used_count == 1