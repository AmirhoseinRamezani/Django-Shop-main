# tests/e2e/test_outbox_pipeline.py
import pytest

from events.bus import publish
from events.models import OutboxStatus
from events.services.processor import process_outbox


pytestmark = pytest.mark.django_db


class TestOutboxPipeline:

    def test_complete_pipeline(
        self,
        mocker,
    ):
        dispatch = mocker.patch(
            "events.services.processor.dispatch"
        )

        publish(
            topic="order.paid",
            payload={
                "order_id": 10,
            },
        )

        process_outbox()

        dispatch.assert_called_once()

        from events.models import OutboxEvent

        event = OutboxEvent.objects.get()

        assert event.status == OutboxStatus.processed
