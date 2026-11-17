import pytest

from django.core.exceptions import ValidationError

from order.models import OrderModel, OrderStatusType
from order.services.state_machine import OrderStateMachine


pytestmark = pytest.mark.django_db


def test_model_save_cannot_bypass_order_state_machine(pending_order):
    pending_order.status = OrderStatusType.failed

    with pytest.raises(
        ValidationError,
        match="OrderStateMachine",
    ):
        pending_order.save(update_fields=("status",))

    pending_order.refresh_from_db()
    assert pending_order.status == OrderStatusType.pending


def test_queryset_update_cannot_bypass_order_state_machine(pending_order):
    with pytest.raises(
        ValidationError,
        match="OrderStateMachine",
    ):
        OrderModel.objects.filter(pk=pending_order.pk).update(
            status=OrderStatusType.failed,
        )

    pending_order.refresh_from_db()
    assert pending_order.status == OrderStatusType.pending


def test_bulk_update_cannot_bypass_order_state_machine(pending_order):
    pending_order.status = OrderStatusType.failed

    with pytest.raises(
        ValidationError,
        match="OrderStateMachine",
    ):
        OrderModel.objects.bulk_update(
            [pending_order],
            ["status"],
        )

    pending_order.refresh_from_db()
    assert pending_order.status == OrderStatusType.pending


def test_non_status_queryset_update_remains_supported(pending_order):
    updated = OrderModel.objects.filter(
        pk=pending_order.pk,
    ).update(
        full_name="Updated Customer",
    )

    assert updated == 1

    pending_order.refresh_from_db()
    assert pending_order.full_name == "Updated Customer"


def test_canonical_state_machine_transition_still_works(
    pending_order,
    mocker,
):
    mocker.patch(
        "order.services.state_machine.InventoryService.restore"
    )
    mocker.patch(
        "order.services.state_machine.record_order_event"
    )

    order = OrderStateMachine.transition(
        order=pending_order,
        to_status=OrderStatusType.cancelled,
    )

    order.refresh_from_db()
    assert order.status == OrderStatusType.cancelled