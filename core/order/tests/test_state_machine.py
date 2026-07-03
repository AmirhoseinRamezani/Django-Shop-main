# order/tests/test_state_machine.py
import pytest
from django.core.exceptions import ValidationError

from order.services.state_machine import (
    OrderStateMachine
)

from order.models import (
    OrderStatusType
)


@pytest.mark.django_db
def test_pending_to_cancelled(
    pending_order,
):
    OrderStateMachine.transition(
        order=pending_order,
        to_status=OrderStatusType.cancelled,
    )

    pending_order.refresh_from_db()

    assert (
        pending_order.status
        == OrderStatusType.cancelled
    )


@pytest.mark.django_db
def test_invalid_transition(
    pending_order,
):
    

    with pytest.raises(ValidationError):
        OrderStateMachine.transition(
            order=pending_order,
            to_status=OrderStatusType.refunded,
        )
