# tests/e2e/test_order_cancel.py
import pytest

from order.models import OrderStatusType
from order.services.state_machine import OrderStateMachine
from order.services.inventory import InventoryService


pytestmark = pytest.mark.django_db


def test_cancel_restores_inventory(
    order_with_items,
):

    product = order_with_items.order_items.first().product

    before = product.stock
    InventoryService.reserve(order_with_items)

    OrderStateMachine.transition(
        order=order_with_items,
        to_status=OrderStatusType.cancelled,
    )

    product.refresh_from_db()

    assert product.stock == before