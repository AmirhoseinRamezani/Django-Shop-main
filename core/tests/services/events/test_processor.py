# tests/services/events/test_processor.py
import pytest
from datetime import timedelta
from unittest.mock import Mock
from django.utils import timezone

from events.models.outbox import OutboxEvent, OutboxStatus
from events.services.processor import process_outbox


pytestmark = pytest.mark.django_db

class TestProcessor:

    def test_processed(self, outbox_event, mocker):
        dispatch = mocker.patch("events.services.processor.dispatch")
        result = process_outbox()

        outbox_event.refresh_from_db()

        dispatch.assert_called_once_with(outbox_event)

        assert outbox_event.status == OutboxStatus.processed
        assert outbox_event.retry_count == 0
        assert outbox_event.processed_date is not None
        assert outbox_event.claim_token is None
        assert outbox_event.claimed_at is None
        assert result.claimed == result.processed == 1

    def test_retry_uses_backoff_and_releases_lease(self, outbox_event, mocker):
        mocker.patch(
            "events.services.processor.dispatch",
            side_effect=RuntimeError("boom"),
        )

        result = process_outbox(retry_base_seconds=10, retry_max_seconds=30)

        outbox_event.refresh_from_db()

        assert outbox_event.status == OutboxStatus.pending
        assert outbox_event.retry_count == 1
        assert outbox_event.last_error == "RuntimeError: boom"
        assert outbox_event.available_at >= timezone.now() + timedelta(seconds=9)
        assert outbox_event.claim_token is None
        assert outbox_event.claimed_at is None
        assert result.retried == 1


    def test_failed_after_retry(self, outbox_event, mocker):
        outbox_event.retry_count = 4
        outbox_event.save(update_fields=["retry_count"])

        mocker.patch(
            "events.services.processor.dispatch",
            side_effect=RuntimeError("boom"),
        )

        result = process_outbox()

        outbox_event.refresh_from_db()

        assert outbox_event.status == OutboxStatus.failed
        assert outbox_event.retry_count == 5
        assert result.failed == 1

    def test_ignore_processed(self, outbox_event, mocker):
        outbox_event.status = OutboxStatus.processed
        outbox_event.save(update_fields=["status"])
        dispatch = mocker.patch("events.services.processor.dispatch")

        result = process_outbox()

        dispatch.assert_not_called()
        assert result.claimed == 0

    def test_batch_size(self, mocker):
        for _ in range(10):
            OutboxEvent.objects.create(topic="order.pending", payload={})
        dispatch = mocker.patch("events.services.processor.dispatch")

        result = process_outbox(batch_size=3)

        assert dispatch.call_count == 3
        assert result.claimed == 3

    def test_expired_claim_is_recovered(self, outbox_event, mocker):
        outbox_event.status = OutboxStatus.processing
        outbox_event.claimed_at = timezone.now() - timedelta(minutes=10)
        outbox_event.claim_token = "11111111-1111-4111-8111-111111111111"
        outbox_event.save(update_fields=["status", "claimed_at", "claim_token"])
        dispatch = mocker.patch("events.services.processor.dispatch")

        result = process_outbox(lease_seconds=60)

        outbox_event.refresh_from_db()
        dispatch.assert_called_once()
        assert outbox_event.status == OutboxStatus.processed
        assert result.processed == 1

    def test_stale_worker_cannot_acknowledge_reclaimed_event(self, outbox_event, mocker):
        import uuid

        def simulate_reclaim(event):
            OutboxEvent.objects.filter(pk=event.pk).update(
                claim_token=uuid.uuid4(),
            )

        mocker.patch(
            "events.services.processor.dispatch",
            side_effect=simulate_reclaim,
        )

        result = process_outbox()

        outbox_event.refresh_from_db()
        assert outbox_event.status == OutboxStatus.processing
        assert result.lost_claims == 1
        assert result.processed == 0

    def test_invalid_options_are_rejected(self):
        with pytest.raises(ValueError, match="batch_size"):
            process_outbox(batch_size=0)