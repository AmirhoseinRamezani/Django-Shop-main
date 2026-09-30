# tests/integration/test_order_cancel_flow.py
import pytest

from order.models import OrderStatusType
from order.services.state_machine import OrderStateMachine
from order.services.inventory import InventoryService


pytestmark = pytest.mark.django_db(transaction=True)


def test_cancel_restores_stock(
    order,
    order_item,
):
    product = order_item.product

    before = product.stock

    InventoryService.reserve(order)

    product.refresh_from_db()
    assert product.stock == before - order_item.quantity

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.cancelled,
    )

    product.refresh_from_db()

    assert product.stock == before