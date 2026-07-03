# tests/integration/test_cancel_order_flow.py
import pytest

from order.models import OrderStatusType
from order.services.state_machine import OrderStateMachine

from tests.assertions import (
    refresh,
    assert_stock_restored,
)

pytestmark = pytest.mark.django_db


class TestCancelFlow:

    def test_cancel_restores_inventory(
        self,
        order_builder,
        product,
    ):
        initial_stock = product.stock

        order = (
            order_builder
            .with_item(product, quantity=4)
            .build()
        )

        product.stock -= 4
        product.save(update_fields=["stock"])

        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
        )

        refresh(order, product)

        assert order.status == OrderStatusType.cancelled

        assert_stock_restored(
            product,
            initial_stock,
        )

    def test_paid_order_cannot_cancel(
        self,
        paid_order,
    ):
        with pytest.raises(Exception):
            OrderStateMachine.transition(
                order=paid_order,
                to_status=OrderStatusType.cancelled,
            )