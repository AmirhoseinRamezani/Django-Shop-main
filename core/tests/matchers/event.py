# tests/matchers/event.py
from events.models import (
    OutboxEvent,
)


def latest(topic):

    event = (
        OutboxEvent.objects
        .order_by("-id")
        .first()
    )

    assert event

    assert event.topic == topic

    return event
