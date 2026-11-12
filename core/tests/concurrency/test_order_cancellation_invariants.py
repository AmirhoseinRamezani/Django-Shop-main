# tests/concurrency/test_order_cancellation_invariants.py
from datetime import timedelta
from io import StringIO

import pytest

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from order.events.order_event import OrderEvent, OrderEventType
from order.models import (
    CouponReservation,
    CouponReservationStatus,
    InventoryReservation,
    InventoryReservationStatus,
    OrderStatusType,
)
from order.services.inventory import InventoryService
from order.services.coupon import CouponService
from order.services.state_machine import OrderStateMachine
from order.services.confirm_payment import confirm_order_payment
from tests.concurrency.base import ConcurrentRunner
from tests.factories.order import OrderFactory, OrderItemFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory
from tests.factories.shop import CouponFactory, ProductFactory


pytestmark = pytest.mark.django_db(transaction=True)


def test_canonical_cancellation_persists_cancelled_date(order):
    """Canonical cancellation persists its terminal timestamp."""

    InventoryService.reserve(order)

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.cancelled,
    )

    order.refresh_from_db()

    assert order.status == OrderStatusType.cancelled
    assert order.cancelled_date is not None
    assert order.paid_date is None


def test_cancelled_order_keeps_terminal_timestamp(order):
    """A repeated cancellation cannot clear or replace its timestamp."""

    InventoryService.reserve(order)

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.cancelled,
    )

    order.refresh_from_db()
    cancelled_date = order.cancelled_date

    with pytest.raises(ValidationError):
        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
        )

    order.refresh_from_db()

    assert order.status == OrderStatusType.cancelled
    assert order.cancelled_date == cancelled_date


def test_model_cancellation_delegates_to_state_machine(
    monkeypatch,
):
    """The model method delegates lifecycle changes to the state machine."""

    order = OrderFactory()
    calls = {}

    def transition(*, order, to_status, **kwargs):
        calls["order_id"] = order.pk
        calls["to_status"] = to_status
        return order

    monkeypatch.setattr(
        OrderStateMachine,
        "transition",
        transition,
    )

    result = order.mark_cancelled()

    assert result.pk == order.pk
    assert calls == {
        "order_id": order.pk,
        "to_status": OrderStatusType.cancelled,
    }


def test_paid_order_cannot_be_cancelled_through_model_method():
    """A paid order cannot bypass the canonical transition rules."""

    order = OrderFactory(paid=True)

    with pytest.raises(ValidationError):
        order.mark_cancelled()

    order.refresh_from_db()

    assert order.status == OrderStatusType.paid
    assert order.cancelled_date is None


def test_pending_order_can_be_cancelled_through_model_method(order):
    """A valid pending-order cancellation persists the expected state."""

    InventoryService.reserve(order)

    result = order.mark_cancelled()

    result.refresh_from_db()

    assert result.status == OrderStatusType.cancelled
    assert result.cancelled_date is not None
    assert result.paid_date is None


def test_processing_order_cancellation_is_rejected_without_inventory_mutation():
    product = ProductFactory(stock=8)
    order = OrderFactory()
    item = OrderItemFactory(
        order=order,
        product=product,
        quantity=2,
    )
    InventoryService.reserve(order)
    product.refresh_from_db()
    stock_after_reservation = product.stock

    payment = PaymentFactory(order=order, success=True)
    PaymentAttemptFactory(payment=payment, success=True)

    confirm_order_payment(order.pk, payment.pk)

    reservation = InventoryReservation.objects.get(order_item=item)
    assert reservation.status == InventoryReservationStatus.CONSUMED

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.processing,
    )
    with pytest.raises(ValidationError, match="Illegal transition"):
        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
        )

    order.refresh_from_db()
    product.refresh_from_db()
    reservation.refresh_from_db()

    assert order.status == OrderStatusType.processing
    assert reservation.status == InventoryReservationStatus.CONSUMED
    assert reservation.consumed_at is not None
    assert reservation.released_at is None
    assert product.stock == stock_after_reservation


def test_canonical_paid_payment_prevents_release_of_legacy_reserved_row():
    product = ProductFactory(stock=8)
    order = OrderFactory()
    item = OrderItemFactory(order=order, product=product, quantity=2)
    InventoryService.reserve(order)
    product.refresh_from_db()
    stock_after_reservation = product.stock

    payment = PaymentFactory(order=order, success=True)
    PaymentAttemptFactory(payment=payment, success=True)
    confirm_order_payment(order.pk, payment.pk)

    # Simulate a legacy row left RESERVED by the pre-consumption implementation.
    reservation = InventoryReservation.objects.get(order_item=item)
    reservation.status = InventoryReservationStatus.RESERVED
    reservation.consumed_at = None
    reservation.save(update_fields=("status", "consumed_at"))

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.processing,
    )
    with pytest.raises(ValidationError, match="Illegal transition"):
        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
        )

    order.refresh_from_db()
    reservation.refresh_from_db()
    product.refresh_from_db()

    assert order.status == OrderStatusType.processing
    assert reservation.status == InventoryReservationStatus.RESERVED
    assert reservation.consumed_at is None
    assert product.stock == stock_after_reservation


def test_concurrent_expiration_workers_release_order_once():
    coupon = CouponFactory(max_limit_usage=1)
    product = ProductFactory(stock=5)
    order = OrderFactory(
        payable=True,
        coupon=coupon,
        coupon_code=coupon.code,
        coupon_discount_percent=coupon.discount_percent,
    )
    item = OrderItemFactory(
        order=order,
        product=product,
        quantity=2,
    )

    InventoryService.reserve(order)
    CouponService.reserve_for_order(order)

    order.expire_at = timezone.now() - timedelta(minutes=1)
    order.save(update_fields=("expire_at",))

    def expire_orders():
        call_command("expire_pending_orders", stdout=StringIO())

    ConcurrentRunner().run(expire_orders, expire_orders)

    order.refresh_from_db()
    product.refresh_from_db()
    coupon.refresh_from_db()
    inventory_reservation = InventoryReservation.objects.get(order_item=item)
    coupon_reservation = CouponReservation.objects.get(order=order)

    assert order.status == OrderStatusType.cancelled
    assert order.cancelled_date is not None
    assert product.stock == 5
    assert inventory_reservation.status == InventoryReservationStatus.RELEASED
    assert coupon_reservation.status == CouponReservationStatus.RELEASED
    assert coupon.reserved_count == 0
    assert coupon.used_count == 0
    assert OrderEvent.objects.filter(
        order=order,
        type=OrderEventType.EXPIRED,
    ).count() == 1