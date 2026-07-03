# tests/performance/test_query_count.py

import pytest

from tests.helpers.queries import (
    assert_max_queries,
)

from order.services.order import OrderService


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.performance,
]


class TestOrderQueries:

    def test_create_order_queries(
        self,
        user,
        address,
        cart_builder,
        product,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product, quantity=2)
            .build()
        )

        assert_max_queries(
            12,
            OrderService.create_online_order,
            user=user,
            address=address,
            cart=cart,
        )

    def test_multiple_products_queries(
        self,
        user,
        address,
        product_factory,
        cart_builder,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product_factory(), 1)
            .with_item(product_factory(), 2)
            .with_item(product_factory(), 3)
            .build()
        )

        assert_max_queries(
            15,
            OrderService.create_online_order,
            user=user,
            address=address,
            cart=cart,
        )

