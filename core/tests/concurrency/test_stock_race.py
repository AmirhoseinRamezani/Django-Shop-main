import pytest

from tests.concurrency.base import ConcurrentRunner
from tests.builders.cart_builder import CartBuilder
from tests.factories.accounts import UserFactory
from tests.factories.shop import AddressFactory, ProductFactory
from order.services.order import OrderService
from order.models import OrderModel


pytestmark = pytest.mark.django_db(transaction=True)


def test_stock_locking():
    product = ProductFactory(stock=1)

    user1 = UserFactory()
    user2 = UserFactory()

    address1 = AddressFactory(user=user1)
    address2 = AddressFactory(user=user2)

    cart1 = CartBuilder().for_user(user1).with_item(product).build()
    cart2 = CartBuilder().for_user(user2).with_item(product).build()

    results = []

    def checkout(user, address, cart):
        try:
            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )
            results.append(True)
        except Exception:
            results.append(False)

    runner = ConcurrentRunner()
    runner.run(
        lambda: checkout(user1, address1, cart1),
        lambda: checkout(user2, address2, cart2),
    )

    product.refresh_from_db()

    assert product.stock == 0
    assert sum(results) == 1
    assert OrderModel.objects.filter(
        order_items__product=product,
    ).distinct().count() == 1
