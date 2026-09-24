import pytest

from tests.concurrency.base import ConcurrentRunner
from tests.factories.accounts import UserFactory
from tests.factories.shop import AddressFactory, ProductFactory
from tests.builders.cart_builder import CartBuilder

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
