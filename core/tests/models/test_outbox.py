# tests/models/test_outbox.py
import pytest

from events.models import OutboxStatus

pytestmark = pytest.mark.django_db

class TestOutboxModel:

    def test_default_status(
        self,
        outbox_event,
    ):

        assert outbox_event.status == OutboxStatus.pending

    def test_default_retry(
        self,
        outbox_event,
    ):

        assert outbox_event.retry_count == 0

    def test_topic(self, outbox_event):

        assert outbox_event.topic

    def test_payload(self, outbox_event):

        assert isinstance(
            outbox_event.payload,
            dict,
        )

    def test_string(self, outbox_event):

        assert str(outbox_event)