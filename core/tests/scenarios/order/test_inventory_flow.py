# tests/scenarios/order/test_inventory_flow.py
import pytest

from order.services.order import OrderService

pytestmark = pytest.mark.django_db

class TestInventoryFlow:

    def test_multiple_products(
        self,
        user,
        address,
        cart,
        product_factory,
    ):

        p1 = product_factory(stock=10)

        p2 = product_factory(stock=10)

        p3 = product_factory(stock=10)

        cart.add(p1, quantity=2)

        cart.add(p2, quantity=3)

        cart.add(p3, quantity=4)

        OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        p1.refresh_from_db()
        p2.refresh_from_db()
        p3.refresh_from_db()

        assert p1.stock == 8
        assert p2.stock == 7
        assert p3.stock == 6