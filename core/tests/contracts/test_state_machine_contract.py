# tests/contracts/test_state_machine_contract.py
import pytest

from order.models import OrderStatusType
from order.services.state_machine import (
    OrderStateMachine,
)


pytestmark = pytest.mark.django_db


def test_all_statuses_exist_in_transition_table():

    statuses = {

        status.value

        for status in OrderStatusType

    }

    assert statuses == set(
        OrderStateMachine.TRANSITIONS.keys()
    )