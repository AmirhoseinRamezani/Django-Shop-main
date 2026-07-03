# tests/contracts/test_order_events_contract.py
import pytest

from events.dispatchers.registry import ROUTES


pytestmark = pytest.mark.django_db


REQUIRED = {
    "order.created",
    "order.paid",
    "order.cancelled",
}


def test_order_topics_registered():

    for topic in REQUIRED:

        assert topic in ROUTES

        assert ROUTES[topic]