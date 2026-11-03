# tests/contracts/test_outbox_topics.py
from events.dispatchers.registry import NOOP_TOPICS, ROUTES


def test_topics_are_unique():
    assert len(ROUTES) == len(set(ROUTES))
    assert len(NOOP_TOPICS) == len(set(NOOP_TOPICS))
    assert not (set(ROUTES) & set(NOOP_TOPICS))

def test_every_registered_route_has_handlers():
    assert all(handlers for handlers in ROUTES.values())    