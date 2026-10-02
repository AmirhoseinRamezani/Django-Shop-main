# tests/concurrency/test_order_cancellation_invariants.py
import pytest

from django.core.exceptions import ValidationError

from order.models import OrderStatusType
from order.services.inventory import InventoryService
from order.services.state_machine import OrderStateMachine


pytestmark = pytest.mark.django_db(transaction=True)


def test_canonical_cancellation_persists_cancelled_date(order):
    """A canonical cancellation records its terminal timestamp."""

    InventoryService.reserve(order)

    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.cancelled,
    )

    order.refresh_from_db()

    assert order.status == OrderStatusType.cancelled
    assert order.cancelled_date is not None
    assert order.paid_date is None


def test_cancelled_order_keeps_terminal_timestamp(order):
    """A second cancellation cannot clear the terminal timestamp."""

    InventoryService.reserve(order)
    OrderStateMachine.transition(
        order=order,
        to_status=OrderStatusType.cancelled,
    )

    order.refresh_from_db()
    cancelled_date = order.cancelled_date

    with pytest.raises(ValidationError):
        OrderStateMachine.transition(
            order=order,
            to_status=OrderStatusType.cancelled,
        )

    order.refresh_from_db()
    assert order.status == OrderStatusType.cancelled
    assert order.cancelled_date == cancelled_date
