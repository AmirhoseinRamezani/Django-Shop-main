# tests/concurrency/test_create_order.py
import threading

import pytest

from order.services.order import OrderService

pytestmark = pytest.mark.django_db(transaction=True)


class TestConcurrentCreateOrder:

    def test_stock_never_negative(
        self,
        user_factory,
        address_factory,
        cart_builder,
        product_factory,
    ):
        product = product_factory(
            stock=1,
        )

        user1 = user_factory()
        user2 = user_factory()

        address1 = address_factory(
            user=user1,
        )

        address2 = address_factory(
            user=user2,
        )

        cart1 = (
            cart_builder
            .for_user(user1)
            .with_item(product)
            .build()
        )

        cart2 = (
            cart_builder
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

        t1 = threading.Thread(
            target=buy,
            args=(user1, address1, cart1),
        )

        t2 = threading.Thread(
            target=buy,
            args=(user2, address2, cart2),
        )

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        product.refresh_from_db()

        assert product.stock >= 0
        assert sum(results) == 1