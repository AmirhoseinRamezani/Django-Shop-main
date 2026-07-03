# tests/concurrency/test_outbox_race.py
import pytest

from tests.concurrency.base import (
    ConcurrentRunner,
)

from events.services.processor import (
    process_outbox,
)


pytestmark = pytest.mark.django_db(
    transaction=True,
)


def test_process_twice(
    outbox_event,
):

    runner = ConcurrentRunner()

    runner.run(

        process_outbox,

        process_outbox,
    )

    outbox_event.refresh_from_db()

    assert outbox_event.processed_date
