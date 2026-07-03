# tests/helpers/db.py
from events.models import OutboxEvent


def latest_event():

    return (
        OutboxEvent.objects
        .order_by("-id")
        .first()
    )


def events_count():

    return OutboxEvent.objects.count()


def assert_event(topic):

    event = latest_event()

    assert event is not None

    assert event.topic == topic

    return event

        