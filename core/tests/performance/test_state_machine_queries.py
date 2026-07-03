# tests/performance/test_state_machine_queries.py
import pytest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from order.models import OrderStatusType
from order.services.state_machine import OrderStateMachine


pytestmark = pytest.mark.django_db


def test_transition_query_count(
    paid_order,
):

    with CaptureQueriesContext(connection) as ctx:

        OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.processing,
        )

    assert len(ctx) <= 6