# tests/services/order/test_expire_pending_orders.py
import pytest

from django.core.management import call_command

from tests.base import BaseTestCase


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]


class TestExpirePendingOrders(BaseTestCase):

    def test_expire_order(
        self,
        order_factory,
        order_item_factory,
        product_factory,
    ):
        product = product_factory(
            stock=5,
        )

        order = order_factory(
            expired=True,
        )

        order_item_factory(
            order=order,
            product=product,
            quantity=2,
        )

        product.stock = 3
        product.save()

        call_command(
            "expire_pending_orders"
        )

        self.assert_order_cancelled(
            order
        )

        product.refresh_from_db()

        assert product.stock == 5

    def test_not_expired(
        self,
        order_factory,
    ):
        order = order_factory(
            payable=True,
        )

        call_command(
            "expire_pending_orders"
        )

        order.refresh_from_db()

        assert order.is_payable

    def test_paid_order_not_expired(
        self,
        order_factory,
    ):
        order = order_factory(
            paid=True,
        )

        call_command(
            "expire_pending_orders"
        )

        order.refresh_from_db()

        assert order.is_paid

    def test_multiple_orders(
        self,
        order_factory,
    ):
        expired1 = order_factory(
            expired=True,
        )

        expired2 = order_factory(
            expired=True,
        )

        payable = order_factory(
            payable=True,
        )

        call_command(
            "expire_pending_orders"
        )

        expired1.refresh_from_db()
        expired2.refresh_from_db()
        payable.refresh_from_db()

        assert expired1.is_completed
        assert expired2.is_completed
        assert payable.is_payable