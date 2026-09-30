# tests/e2e/test_order_cancel_timeout.py
import pytest

from order.models import OrderStatusType
from order.services.state_machine import (
    OrderStateMachine,
)
from order.services.inventory import InventoryService


pytestmark = pytest.mark.django_db


class TestTimeout:

    def test_cancel_expired_order(
        self,
        order_builder,
        product,
    ):
        scenario = (
            order_builder
            .with_item(product, quantity=2)
            .build()
        )
        order = scenario.order
        InventoryService.reserve(order)

        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
            payload={
                "reason": "timeout",
            },
        )

        order.refresh_from_db()
        product.refresh_from_db()

        assert order.status == OrderStatusType.cancelled
        assert product.stock >= 2
