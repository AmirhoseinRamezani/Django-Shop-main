#tests/integration/test_outbox_flow.py
import pytest

from events.bus import publish
from events.models import (
    OutboxEvent,
    OutboxStatus,
)
from events.services.processor import process_outbox

pytestmark = pytest.mark.django_db


class TestOutboxFlow:

    def test_publish_to_outbox(
        self,
    ):
        publish(
            topic="user.otp",
            payload={
                "email": "user@test.com",
                "code": "123456",
            },
        )

        assert OutboxEvent.objects.count() == 1

    def test_processor_marks_processed(
        self,
        mocker,
    ):
        publish(
            topic="user.otp",
            payload={
                "email": "user@test.com",
                "code": "123456",
            },
        )

        dispatch = mocker.patch(
            "events.services.processor.dispatch"
        )

        process_outbox()

        event = OutboxEvent.objects.first()

        assert event.status == OutboxStatus.processed

        dispatch.assert_called_once_with(event)

    def test_failed_event_retry(
        self,
        mocker,
    ):
        publish(
            topic="user.otp",
            payload={},
        )

        mocker.patch(
            "events.services.processor.dispatch",
            side_effect=RuntimeError("boom"),
        )

        process_outbox()

        event = OutboxEvent.objects.first()

        assert event.retry_count == 1

        assert event.status == OutboxStatus.pending
