# tests/scenarios/order/test_expire_flow.py
import pytest

from order.services.order import OrderService

from order.models import (
    OrderStatusType,
)

from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta

pytestmark = pytest.mark.django_db

class TestExpireFlow:

    def test_order_expire(
        self,
        user,
        address,
        cart,
        product,
    ):
        initial_stock = product.stock

        cart.add(
            product,
            quantity=2,
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        order.expire_at = (
            timezone.now()
            - timedelta(minutes=1)
        )

        order.save()

        call_command(
            "expire_pending_orders"
        )

        order.refresh_from_db()
        product.refresh_from_db()

        assert order.status == OrderStatusType.cancelled

        assert product.stock == initial_stock
        
        