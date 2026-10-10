# tests/concurrency/test_order_cancellation_invariants.py

import pytest

from django.core.exceptions import ValidationError

from order.models import OrderStatusType
from order.services.inventory import InventoryService
from order.services.state_machine import OrderStateMachine
from tests.factories.order import OrderFactory


pytestmark = pytest.mark.django_db(transaction=True)


def test_canonical_cancellation_persists_cancelled_date(order):
    """Canonical cancellation persists its terminal timestamp."""

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
    """A repeated cancellation cannot clear or replace its timestamp."""

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


def test_model_cancellation_delegates_to_state_machine(
    monkeypatch,
):
    """The model method delegates lifecycle changes to the state machine."""

    order = OrderFactory()
    calls = {}

    def transition(*, order, to_status, **kwargs):
        calls["order_id"] = order.pk
        calls["to_status"] = to_status
        return order

    monkeypatch.setattr(
        OrderStateMachine,
        "transition",
        transition,
    )

    result = order.mark_cancelled()

    assert result.pk == order.pk
    assert calls == {
        "order_id": order.pk,
        "to_status": OrderStatusType.cancelled,
    }


def test_paid_order_cannot_be_cancelled_through_model_method():
    """A paid order cannot bypass the canonical transition rules."""

    order = OrderFactory(paid=True)

    with pytest.raises(ValidationError):
        order.mark_cancelled()

    order.refresh_from_db()

    assert order.status == OrderStatusType.paid
    assert order.cancelled_date is None


def test_pending_order_can_be_cancelled_through_model_method(order):
    """A valid pending-order cancellation persists the expected state."""

    InventoryService.reserve(order)

    result = order.mark_cancelled()

    result.refresh_from_db()

    assert result.status == OrderStatusType.cancelled
    assert result.cancelled_date is not None
    assert result.paid_date is None