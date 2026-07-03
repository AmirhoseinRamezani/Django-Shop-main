# tests/helpers/outbox.py
from events.models import (
    OutboxStatus,
)


def assert_processed(event):

    event.refresh_from_db()

    assert (
        event.status
        ==
        OutboxStatus.processed
    )


def assert_failed(event):

    event.refresh_from_db()

    assert (
        event.status
        ==
        OutboxStatus.failed
    )


def assert_pending(event):

    event.refresh_from_db()

    assert (
        event.status
        ==
        OutboxStatus.pending
    )
