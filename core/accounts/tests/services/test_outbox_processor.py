# accounts/tests/services/test_outbox_processor.py
import pytest
from events.models import OutboxEvent, OutboxStatus
from events.services.processor import process_outbox


@pytest.mark.django_db
def test_outbox_processed_successfully(monkeypatch):
    def fake_dispatch(event):
        return None

    monkeypatch.setattr(
        "events.services.processor.dispatch",
        fake_dispatch,
    )

    event = OutboxEvent.objects.create(
        topic="user.otp",
        payload={"email": "ok@test.com", "code": "1234"},
    )

    process_outbox()

    event.refresh_from_db()
    assert event.status == OutboxStatus.processed
    assert event.retry_count == 0


@pytest.mark.django_db
def test_outbox_fails_after_exception(monkeypatch):
    def broken_dispatch(event):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(
        "events.services.processor.dispatch",
        broken_dispatch,
    )

    event = OutboxEvent.objects.create(
        topic="user.otp",
        payload={"email": "fail@test.com", "code": "9999"},
    )

    process_outbox(max_retry=1)

    event.refresh_from_db()
    assert event.status == OutboxStatus.failed
    assert "smtp down" in event.last_error
