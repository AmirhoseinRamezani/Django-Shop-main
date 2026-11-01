import pytest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from order.models import OrderModel
from order.services.order import OrderService
from tests.builders.cart_builder import CartBuilder

from tests.concurrency.base import ConcurrentRunner

pytestmark = pytest.mark.django_db(transaction=True)


class TestConcurrentCreateOrder:

    def test_stock_never_negative(
        self,
        user_factory,
        address_factory,
        product_factory,
    ):
        product = product_factory(stock=1)

        user1 = user_factory()
        user2 = user_factory()

        address1 = address_factory(user=user1)
        address2 = address_factory(user=user2)

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

        def buy(user, address, cart):
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
            lambda: buy(user1, address1, cart1),
            lambda: buy(user2, address2, cart2),
        )

        product.refresh_from_db()

        assert product.stock >= 0
        assert sum(results) == 1
        assert OrderModel.objects.filter(
            order_items__product=product,
        ).distinct().count() == 1

    def test_checkout_locks_cart_items_without_locking_joined_products(
        self,
        user_factory,
        address_factory,
        product_factory,
        cart_factory,
        cart_item_factory,
    ):
        user = user_factory()
        address = address_factory(user=user)
        cart = cart_factory(user=user)
        products = [
            product_factory(stock=5),
            product_factory(stock=5),
        ]

        for product in products:
            cart_item_factory(
                cart=cart,
                product=product,
                quantity=1,
            )

        with CaptureQueriesContext(connection) as queries:
            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

        cart_lock_query = next(
            (
                query["sql"]
                for query in queries
                if 'FROM "cart_cartitemmodel"' in query["sql"]
                and "FOR UPDATE" in query["sql"]
            ),
            None,
        )

        assert cart_lock_query is not None
        assert 'FOR UPDATE OF "cart_cartitemmodel"' in cart_lock_query
