# tests/performance/test_outbox_queries.py
import pytest

from tests.helpers.queries import (
    assert_max_queries,
)

from events.services.processor import process_outbox


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.performance,
]


class TestOutboxQueries:

    def test_process_single_event(
        self,
        outbox_event,
        mocker,
    ):
        mocker.patch(
            "events.services.processor.dispatch",
        )

        assert_max_queries(
            5,
            process_outbox,
        )

    def test_process_batch(
        self,
        outbox_event_factory,
        mocker,
    ):
        for _ in range(20):
            outbox_event_factory()

        mocker.patch(
            "events.services.processor.dispatch",
        )

        assert_max_queries(
            30,
            process_outbox,
            batch_size=20,
        )