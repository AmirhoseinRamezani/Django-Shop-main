# tests/matchers/outbox.py
from events.models import (
    OutboxStatus,
)


def processed(event):

    event.refresh_from_db()

    assert (
        event.status
        ==
        OutboxStatus.processed
    )


def failed(event):

    event.refresh_from_db()

    assert (
        event.status
        ==
        OutboxStatus.failed
    )
