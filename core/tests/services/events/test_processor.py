# tests/services/events/test_processor.py
import pytest

from events.models.outbox import (
    OutboxEvent,
    OutboxStatus,
)

from events.services.processor import process_outbox

pytestmark = pytest.mark.django_db


class TestProcessor:

    def test_processed(
        self,
        outbox_event,
        mocker,
    ):
        dispatch = mocker.patch(
            "events.services.processor.dispatch",
        )

        process_outbox()

        outbox_event.refresh_from_db()

        dispatch.assert_called_once_with(
            outbox_event,
        )

        assert outbox_event.status == OutboxStatus.processed
        assert outbox_event.retry_count == 0
        assert outbox_event.processed_date is not None

    def test_retry(
        self,
        outbox_event,
        mocker,
    ):
        mocker.patch(
            "events.services.processor.dispatch",
            side_effect=Exception("boom"),
        )

        process_outbox()

        outbox_event.refresh_from_db()

        assert outbox_event.status == OutboxStatus.pending
        assert outbox_event.retry_count == 1
        assert outbox_event.last_error == "boom"

    def test_failed_after_retry(
        self,
        outbox_event,
        mocker,
    ):
        outbox_event.retry_count = 4
        outbox_event.save(update_fields=["retry_count"])

        mocker.patch(
            "events.services.processor.dispatch",
            side_effect=Exception("boom"),
        )

        process_outbox()

        outbox_event.refresh_from_db()

        assert outbox_event.status == OutboxStatus.failed
        assert outbox_event.retry_count == 5

    def test_ignore_processed(
        self,
        outbox_event,
        mocker,
    ):
        outbox_event.status = OutboxStatus.processed
        outbox_event.save(update_fields=["status"])

        dispatch = mocker.patch(
            "events.services.processor.dispatch",
        )

        process_outbox()

        dispatch.assert_not_called()

    def test_batch_size(
        self,
        mocker,
    ):
        for _ in range(10):
            OutboxEvent.objects.create(
                topic="user.otp",
                payload={},
            )

        dispatch = mocker.patch(
            "events.services.processor.dispatch",
        )

        process_outbox(batch_size=3)

        assert dispatch.call_count == 3