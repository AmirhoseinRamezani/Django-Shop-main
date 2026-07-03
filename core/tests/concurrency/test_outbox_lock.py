# tests/concurrency/test_outbox_lock.py
import threading

import pytest

from events.services.processor import process_outbox
from events.models import (
    OutboxEvent,
    OutboxStatus,
)


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.concurrency,
]


def worker():

    process_outbox()


def test_outbox_processed_once(outbox_event):

    t1 = threading.Thread(target=worker)

    t2 = threading.Thread(target=worker)

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    outbox_event.refresh_from_db()

    assert outbox_event.status == OutboxStatus.processed

    assert (
        OutboxEvent.objects.filter(
            status=OutboxStatus.processed,
        ).count()
        == 1
    )
