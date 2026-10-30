# tests/concurrency/test_coupon_race.py
from __future__ import annotations

import queue
import threading

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections

from order.events.order_event import OrderEventType
from cart.models import CartModel
from accounts.models import User
from order.models import (
    CouponModel,
    InventoryReservation,
    CouponReservation,
    CouponReservationReconciliation,
    CouponReservationStatus,
    CouponReconciliationStatus,
    OrderStatusType,
)
from order.services.confirm_payment import confirm_order_payment
from order.services.coupon import CouponService
from order.services.order import OrderService
from order.models import OrderItemModel, OrderModel
from payment.enums import PaymentAttemptStatus
from tests.factories.order import OrderFactory
from tests.factories.cart import CartFactory, CartItemFactory
from tests.factories.accounts import UserFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory
from tests.factories.shop import AddressFactory, CouponFactory, ProductFactory


pytestmark = pytest.mark.django_db(transaction=True)


def _build_paid_payment(order):
    payment = PaymentFactory(order=order, success=True)
    attempt = PaymentAttemptFactory(payment=payment, success=True)

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
        threading.Thread(target=worker, args=(index, target))
        for index, target in enumerate(targets)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert all(not thread.is_alive() for thread in threads), "Concurrent worker did not terminate."
    results = dict(outcomes.get_nowait() for _ in threads)
    assert len(results) == len(threads)
    return results


def test_concurrent_checkout_last_coupon_slot_rolls_back_loser_fully():
    coupon = CouponFactory(max_limit_usage=1, used_count=0)
    product = ProductFactory(stock=10)
    checkout_inputs = []
    for _ in range(2):
        user = UserFactory()
        address = AddressFactory(user=user)
        cart = CartFactory(user=user)
        CartItemFactory(cart=cart, product=product, quantity=1)
        checkout_inputs.append((user.pk, address.pk, cart.pk))

    def checkout(input_ids):
        user_id, address_id, cart_id = input_ids
        from order.models import UserAddressModel
        user = User.objects.get(pk=user_id)
        address = UserAddressModel.objects.get(pk=address_id)
        cart = CartModel.objects.get(pk=cart_id)
        return OrderService.create_online_order(
            user=user, address=address, cart=cart, coupon=CouponModel.objects.get(pk=coupon.pk)
        )
    results = _run_concurrently(
        lambda: checkout(checkout_inputs[0]),
        lambda: checkout(checkout_inputs[1]),
    )
    successes = [value for value in results.values() if not isinstance(value, BaseException)]
    failures = [value for value in results.values() if isinstance(value, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ValidationError)

    coupon.refresh_from_db()
    product.refresh_from_db()
    assert OrderModel.objects.filter(coupon=coupon).count() == 1
    assert OrderItemModel.objects.filter(order__coupon=coupon).count() == 1
    assert InventoryReservation.objects.filter(order_item__order__coupon=coupon).count() == 1
    assert CouponReservation.objects.filter(coupon=coupon, status=CouponReservationStatus.RESERVED).count() == 1
    assert coupon.reserved_count == 1
    assert product.stock == 9

def test_last_coupon_slot_is_reserved_by_exactly_one_order():
    coupon = CouponFactory(max_limit_usage=1, used_count=0)
    orders = [
        OrderFactory(coupon=coupon, coupon_code=coupon.code,
                     coupon_discount_percent=coupon.discount_percent)
        for _ in range(2)
    ]
    results = _run_concurrently(
        lambda: CouponService.reserve_for_order(orders[0]),
        lambda: CouponService.reserve_for_order(orders[1]),
    )
    successes = [value for value in results.values() if not isinstance(value, BaseException)]
    failures = [value for value in results.values() if isinstance(value, BaseException)]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ValidationError)

    coupon.refresh_from_db()
    assert coupon.used_count == 0
    assert coupon.reserved_count == 1
    assert CouponReservation.objects.filter(coupon=coupon, status=CouponReservationStatus.RESERVED).count() == 1
    assert CouponReservationReconciliation.objects.filter(coupon=coupon).count() == 1

def test_reserving_same_order_twice_is_idempotent():
    coupon = CouponFactory(max_limit_usage=1)
    order = OrderFactory(coupon=coupon, coupon_code=coupon.code, coupon_discount_percent=coupon.discount_percent)

    first = CouponService.reserve_for_order(order)
    second = CouponService.reserve_for_order(order)

    coupon.refresh_from_db()
    assert first.pk == second.pk
    assert coupon.reserved_count == 1
    assert CouponReservation.objects.filter(order=order).count() == 1


def test_reservation_revalidates_coupon_terms_under_lock():
    coupon = CouponFactory(max_limit_usage=1)
    order = OrderFactory(
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    coupon.discount_percent = coupon.discount_percent + 1
    coupon.save(update_fields=("discount_percent",))

    with pytest.raises(ValidationError, match="terms changed"):
        CouponService.reserve_for_order(order)

    coupon.refresh_from_db()
    assert coupon.reserved_count == 0
    assert CouponReservation.objects.filter(order=order).count() == 0

def test_different_orders_never_share_reservation_identity():
    coupon = CouponFactory(max_limit_usage=2)
    orders = [
        OrderFactory(coupon=coupon, coupon_code=coupon.code, coupon_discount_percent=coupon.discount_percent)
        for _ in range(2)
    ]
    reservations = [CouponService.reserve_for_order(order) for order in orders]

    assert reservations[0].pk != reservations[1].pk
    assert reservations[0].order_id != reservations[1].order_id
    assert CouponReservation.objects.filter(coupon=coupon).count() == 2
    coupon.refresh_from_db()
    assert coupon.reserved_count == 2


def test_repeated_confirmation_consumes_coupon_once():
    coupon = CouponFactory(max_limit_usage=1)
    order = OrderFactory(
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    CouponService.reserve_for_order(order)
    payment, attempt = _build_paid_payment(order)
    first_result = confirm_order_payment(order.pk, payment.pk)
    second_result = confirm_order_payment(order.pk, payment.pk)

    coupon.refresh_from_db()
    order.refresh_from_db()
    payment.refresh_from_db()
    attempt.refresh_from_db()
    reservation = CouponReservation.objects.get(order=order)

    assert first_result.status == OrderStatusType.paid
    assert second_result.status == OrderStatusType.paid
    assert order.status == OrderStatusType.paid
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert coupon.used_count == 1
    assert coupon.reserved_count == 0
    assert reservation.status == CouponReservationStatus.CONSUMED
    assert order.events.filter(type=OrderEventType.PAID).count() == 1

def test_coupon_accounting_failure_does_not_rollback_verified_payment():
    coupon = CouponFactory(max_limit_usage=1, used_count=0)
    order = OrderFactory(coupon=coupon, coupon_code=coupon.code, coupon_discount_percent=coupon.discount_percent)
    # Simulate persisted accounting corruption: the reservation exists but its
    # counter was not incremented. Finalization must still commit financial truth.
    reservation = CouponReservation.objects.create(
        order=order,
        coupon=coupon,
        status=CouponReservationStatus.RESERVED,
     )
    reconciliation = CouponReservationReconciliation.objects.create(
        order=order,
        coupon=coupon,
        reservation=reservation,
    )
    payment, attempt = _build_paid_payment(order)

    result = confirm_order_payment(order.pk, payment.pk)

    order.refresh_from_db()
    payment.refresh_from_db()
    attempt.refresh_from_db()
    coupon.refresh_from_db()
    reservation.refresh_from_db()
    reconciliation.refresh_from_db()

    assert result.status == OrderStatusType.paid
    assert order.status == OrderStatusType.paid
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert order.events.filter(type=OrderEventType.PAID).count() == 1
    assert reservation.status == CouponReservationStatus.RESERVED
    assert coupon.used_count == 0
    assert coupon.reserved_count == 0
    assert reconciliation.status == CouponReconciliationStatus.RETRY
    assert reconciliation.payment_id == payment.pk
    assert reconciliation.attempt_id == attempt.pk
    assert reconciliation.failure_reason


def test_repeated_release_is_idempotent():
    coupon = CouponFactory(max_limit_usage=1)
    order = OrderFactory(coupon=coupon, coupon_code=coupon.code, coupon_discount_percent=coupon.discount_percent)
    CouponService.reserve_for_order(order)

    from order.services.state_machine import OrderStateMachine
    OrderStateMachine.transition(order=order, to_status=OrderStatusType.cancelled)
    assert CouponService.reconcile_order(order.pk) is True
    assert CouponService.reconcile_order(order.pk) is True

    coupon.refresh_from_db()
    reservation = CouponReservation.objects.get(order=order)
    assert coupon.reserved_count == 0
    assert coupon.used_count == 0
    assert reservation.status == CouponReservationStatus.RELEASED
