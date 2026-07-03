# tests/integration/test_outbox_retry.py
import pytest

from events.models.outbox import (
    OutboxStatus,
)
from events.services.processor import process_outbox


pytestmark = pytest.mark.django_db(transaction=True)


def test_retry_until_success(
    outbox_event,
    mocker,
):
    calls = {
        "count": 0,
    }

    def fake_dispatch(event):

        calls["count"] += 1

        if calls["count"] < 3:
            raise Exception("temporary")

    mocker.patch(
        "events.services.processor.dispatch",
        side_effect=fake_dispatch,
    )

    process_outbox()

    outbox_event.refresh_from_db()

    assert outbox_event.retry_count == 1

    process_outbox()
    process_outbox()

    outbox_event.refresh_from_db()

    assert outbox_event.status == OutboxStatus.processed