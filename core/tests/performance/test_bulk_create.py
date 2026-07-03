# tests/performance/test_bulk_create.py
import pytest

from unittest.mock import patch

from order.services.order import OrderService


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.performance,
]


class TestBulkCreate:

    @patch(
        "order.models.OrderItemModel.objects.bulk_create",
    )
    def test_bulk_create_used(
        self,
        bulk_create,
        user,
        address,
        cart_builder,
        product_factory,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product_factory(), 1)
            .with_item(product_factory(), 2)
            .with_item(product_factory(), 3)
            .build()
        )

        OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        bulk_create.assert_called_once()