# tests/contracts/test_order_events_contract.py
import pytest

from events.dispatchers.registry import ROUTES
from order.events.order_event import OrderEventType
from order.services.events import _map_order_event_to_topic


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


def test_every_order_event_type_has_an_explicit_outbox_topic():
    for event_type, _label in OrderEventType.choices:
        topic = _map_order_event_to_topic(event_type)

        assert topic.startswith("order.")
        assert topic != "order.unknown"