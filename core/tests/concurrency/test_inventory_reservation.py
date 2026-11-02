import pytest
from django.core.exceptions import ValidationError

from tests.concurrency.base import ConcurrentRunner
from tests.factories.accounts import UserFactory
from tests.factories.shop import AddressFactory, ProductFactory
from tests.builders.cart_builder import CartBuilder
from tests.factories.order import (
    OrderFactory,
    OrderItemFactory,
)

from order.models import (
    InventoryReservation,
    InventoryReservationStatus,
    OrderModel,
    OrderStatusType,
)
from order.services.inventory import InventoryService
from order.services.order import OrderService
from order.services.state_machine import OrderStateMachine


pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_cancel_releases_inventory_once():
    product = ProductFactory(stock=10)
    user = UserFactory()
    address = AddressFactory(user=user)
    cart = CartBuilder().for_user(user).with_item(product).build()

    order = OrderService.create_online_order(
        user=user,
        address=address,
        cart=cart,
    )

    results = []

    def cancel():
        try:
            OrderStateMachine.transition(
                order=order,
                to_status=OrderStatusType.cancelled,
            )
            results.append(True)
        except Exception:
            results.append(False)

    ConcurrentRunner().run(cancel, cancel)

    product.refresh_from_db()
    order.refresh_from_db()

    assert product.stock == 10
    assert sum(results) == 1
    assert InventoryReservation.objects.filter(
        order_item__order=order,
        status=InventoryReservationStatus.RELEASED,
    ).count() == 1
    assert OrderModel.objects.filter(
        pk=order.pk,
        status=OrderStatusType.cancelled,
    ).exists()


def test_concurrent_reserve_for_same_order_is_idempotent():
    product = ProductFactory(stock=10)
    order = OrderFactory()
    item = OrderItemFactory(
        order=order,
        product=product,
        quantity=3,
    )

    ConcurrentRunner().run(
        lambda: InventoryService.reserve(order),
        lambda: InventoryService.reserve(order),
    )

    product.refresh_from_db()

    assert product.stock == 7
    assert InventoryReservation.objects.filter(
        order_item=item,
        status=InventoryReservationStatus.RESERVED,
        quantity=3,
    ).count() == 1


def test_concurrent_restore_for_same_order_restores_stock_once():
    product = ProductFactory(stock=10)
    order = OrderFactory()
    item = OrderItemFactory(
        order=order,
        product=product,
        quantity=3,
    )
    InventoryService.reserve(order)

    ConcurrentRunner().run(
        lambda: InventoryService.restore(order),
        lambda: InventoryService.restore(order),
    )

    product.refresh_from_db()
    reservation = InventoryReservation.objects.get(order_item=item)

    assert product.stock == 10
    assert reservation.status == InventoryReservationStatus.RELEASED
    assert reservation.quantity == 3


def test_concurrent_reservations_cannot_oversell_last_unit():
    product = ProductFactory(stock=1)
    orders = [OrderFactory(), OrderFactory()]
    items = [
        OrderItemFactory(order=order, product=product, quantity=1)
        for order in orders
    ]
    outcomes = []

    def reserve(order):
        try:
            InventoryService.reserve(order)
        except ValidationError:
            outcomes.append("insufficient")
        else:
            outcomes.append("reserved")

    ConcurrentRunner().run(
        lambda: reserve(orders[0]),
        lambda: reserve(orders[1]),
    )

    product.refresh_from_db()

    assert sorted(outcomes) == ["insufficient", "reserved"]
    assert product.stock == 0
    assert InventoryReservation.objects.filter(
        order_item__in=items,
        status=InventoryReservationStatus.RESERVED,
    ).count() == 1
