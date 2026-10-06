# core/tests/concurrency/test_inventory_consistency.py
import pytest

from django.core.exceptions import ValidationError

from order.models import (
    InventoryReservation,
    InventoryReservationStatus,
    OrderModel,
)
from order.services.inventory import InventoryService
from order.services.order import OrderService
from order.services.state_machine import OrderStateMachine
from order.models import OrderStatusType

from tests.builders.cart_builder import CartBuilder
from tests.concurrency.base import ConcurrentRunner
from tests.factories.accounts import UserFactory
from tests.factories.shop import (
    AddressFactory,
    ProductFactory,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _create_order(*, product, quantity=1):
    user = UserFactory()
    address = AddressFactory(user=user)

    cart = (
        CartBuilder()
        .for_user(user)
        .with_item(product, quantity=quantity)
        .build()
    )

    return OrderService.create_online_order(
        user=user,
        address=address,
        cart=cart,
    )


def test_concurrent_reservation_cannot_oversell():
    product = ProductFactory(stock=1)

    user1 = UserFactory()
    user2 = UserFactory()

    address1 = AddressFactory(user=user1)
    address2 = AddressFactory(user=user2)

    cart1 = (
        CartBuilder()
        .for_user(user1)
        .with_item(product)
        .build()
    )

    cart2 = (
        CartBuilder()
        .for_user(user2)
        .with_item(product)
        .build()
    )

    results = []

    def checkout(user, address, cart):
        try:
            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )
            results.append(True)
        except ValidationError:
            results.append(False)

    ConcurrentRunner().run(
        lambda: checkout(user1, address1, cart1),
        lambda: checkout(user2, address2, cart2),
    )

    product.refresh_from_db()

    assert product.stock == 0
    assert sum(results) == 1

    assert (
        OrderModel.objects
        .filter(order_items__product=product)
        .distinct()
        .count()
        == 1
    )

    assert (
        InventoryReservation.objects
        .filter(
            order_item__product=product,
            status=InventoryReservationStatus.RESERVED,
        )
        .count()
        == 1
    )


def test_reservation_is_exactly_once():
    product = ProductFactory(stock=10)
    order = _create_order(
        product=product,
        quantity=3,
    )

    product.refresh_from_db()

    stock_after_first_reservation = product.stock

    InventoryService.reserve(order)

    product.refresh_from_db()

    assert product.stock == stock_after_first_reservation

    reservation = (
        InventoryReservation.objects
        .get(order_item__order=order)
    )

    assert reservation.quantity == 3
    assert (
        reservation.status
        == InventoryReservationStatus.RESERVED
    )

    assert (
        InventoryReservation.objects
        .filter(order_item__order=order)
        .count()
        == 1
    )


def test_concurrent_restore_releases_inventory_exactly_once():
    product = ProductFactory(stock=10)

    order = _create_order(
        product=product,
        quantity=3,
    )

    product.refresh_from_db()

    assert product.stock == 7

    results = []

    def restore():
        try:
            results.append(
                InventoryService.restore(order)
            )
        except Exception:
            results.append(False)

    ConcurrentRunner().run(
        restore,
        restore,
    )

    product.refresh_from_db()

    reservation = (
        InventoryReservation.objects
        .get(order_item__order=order)
    )

    assert product.stock == 10
    assert sum(results) == 1

    assert (
        reservation.status
        == InventoryReservationStatus.RELEASED
    )



def test_cancelled_order_restores_reserved_stock_once():
    product = ProductFactory(stock=5)

    order = _create_order(
        product=product,
        quantity=2,
    )

    product.refresh_from_db()

    assert product.stock == 3

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.cancelled,
        actor=order.user,
    )

    product.refresh_from_db()
    order.refresh_from_db()

    reservation = (
        InventoryReservation.objects
        .get(order_item__order=order)
    )

    assert order.status == OrderStatusType.cancelled
    assert product.stock == 5
    assert (
        reservation.status
        == InventoryReservationStatus.RELEASED
    )


def test_failed_reservation_rolls_back_all_previous_products():
    product1 = ProductFactory(stock=10)
    product2 = ProductFactory(stock=1)

    user = UserFactory()
    address = AddressFactory(user=user)

    cart = (
        CartBuilder()
        .for_user(user)
        .with_item(product1, quantity=3)
        .with_item(product2, quantity=2)
        .build()
    )

    with pytest.raises(ValidationError):
        OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

    product1.refresh_from_db()
    product2.refresh_from_db()

    assert product1.stock == 10
    assert product2.stock == 1

    assert (
        InventoryReservation.objects
        .filter(
            order_item__product__in=[
                product1,
                product2,
            ],
        )
        .count()
        == 0
    )