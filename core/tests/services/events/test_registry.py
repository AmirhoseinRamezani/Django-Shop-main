# tests/services/events/test_registry.py
from events.dispatchers.registry import NOOP_TOPICS, ROUTES
from order.events.order_event import OrderEventType
from order.services.events import _map_order_event_to_topic


def test_required_topics_registered():

    required = {"user.otp", "order.created", "order.paid", "coupon.used"}
    assert required.issubset(ROUTES)

def test_every_order_event_has_an_explicit_dispatch_policy():
    for event_type, _label in OrderEventType.choices:
        topic = _map_order_event_to_topic(event_type)
        assert topic in ROUTES or topic in NOOP_TOPICS