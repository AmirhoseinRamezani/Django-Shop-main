# tests/integration/test_order_cancel_flow.py
import pytest

from django.db.models import F

from order.models import OrderStatusType
from order.services.state_machine import OrderStateMachine


pytestmark = pytest.mark.django_db(transaction=True)


def test_cancel_restores_stock(
    order,
    order_item,
):
    product = order_item.product

    before = product.stock

    product.stock = F("stock") - order_item.quantity
    product.save(update_fields=["stock"])

    product.refresh_from_db()

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.cancelled,
    )

    product.refresh_from_db()

    assert product.stock == before