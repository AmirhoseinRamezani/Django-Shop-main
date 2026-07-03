# tests/performance/test_select_for_update.py
import pytest

from unittest.mock import patch

from order.services.order import OrderService


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.performance,
]


class TestLocks:

    @patch(
        "shop.models.ProductModel.objects.select_for_update",
    )
    def test_product_locked(
        self,
        select_for_update,
        user,
        address,
        cart_builder,
        product,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product)
            .build()
        )

        try:
            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )
        except Exception:
            pass

        assert select_for_update.called