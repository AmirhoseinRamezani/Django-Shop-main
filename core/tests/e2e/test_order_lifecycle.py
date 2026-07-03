# tests/e2e/test_order_lifecycle.py
import pytest

from order.models import OrderStatusType

from order.services.state_machine import (
    OrderStateMachine,
)

pytestmark = pytest.mark.django_db


class TestLifecycle:

    def test_complete_order_flow(
        self,
        paid_order,
    ):
        OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.processing,
        )

        OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.shipped,
        )

        OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.delivered,
        )

        paid_order.refresh_from_db()

        assert paid_order.status == OrderStatusType.delivered

    def test_return_flow(
        self,
        processing_order,
    ):
        OrderStateMachine.transition(
            order=processing_order,
            to_status=OrderStatusType.shipped,
        )

        OrderStateMachine.transition(
            order=processing_order,
            to_status=OrderStatusType.return_requested,
        )

        OrderStateMachine.transition(
            order=processing_order,
            to_status=OrderStatusType.returned,
        )

        OrderStateMachine.transition(
            order=processing_order,
            to_status=OrderStatusType.refunded,
        )

        processing_order.refresh_from_db()

        assert (
            processing_order.status
            ==
            OrderStatusType.refunded
        )