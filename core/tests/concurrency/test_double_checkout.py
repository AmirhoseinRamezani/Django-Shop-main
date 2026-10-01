import pytest

from tests.concurrency.base import ConcurrentRunner
from tests.factories.shop import AddressFactory, ProductFactory
from tests.builders.cart_builder import CartBuilder
from tests.factories.accounts import UserFactory
from order.services.order import OrderService
from order.models import OrderModel


pytestmark = pytest.mark.django_db(transaction=True)


def test_checkout_twice():
    user = UserFactory()
    address = AddressFactory(user=user)
    product = ProductFactory(stock=2)
    cart = CartBuilder().for_user(user).with_item(product).build()

    runner = ConcurrentRunner()

    runner.run(
        lambda: OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        ),
        lambda: OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        ),
    )

    product.refresh_from_db()

    assert product.stock == 0
    assert OrderModel.objects.filter(user=user).count() == 2
