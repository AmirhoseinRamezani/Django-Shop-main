# tests/e2e/test_order_cancel.py
import pytest

from order.models import OrderStatusType
from order.services.state_machine import OrderStateMachine


pytestmark = pytest.mark.django_db


def test_cancel_restores_inventory(
    order_with_items,
):

    product = order_with_items.order_items.first().product

    before = product.stock

    OrderStateMachine.transition(
        order=order_with_items,
        to_status=OrderStatusType.cancelled,
    )

    product.refresh_from_db()

    assert product.stock > before