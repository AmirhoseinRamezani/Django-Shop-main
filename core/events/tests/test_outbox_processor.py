# events/tests/test_outbox_processor.py
import pytest
from events.models.outbox import OutboxEvent, OutboxStatus
from events.services.processor import process_outbox


@pytest.mark.django_db
def test_outbox_success_path(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    event = OutboxEvent.objects.create(
        topic="user.otp",
        payload={"email": "ok@example.com", "code": "111111"}
    )

    process_outbox()

    event.refresh_from_db()

    assert event.status == OutboxStatus.processed
    assert event.processed_date is not None


@pytest.mark.django_db
def test_outbox_retry_on_failure(monkeypatch):
    def broken_dispatch(event):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(
        "events.services.processor.dispatch",
        broken_dispatch,
    )

    event = OutboxEvent.objects.create(
        topic="user.otp",
        payload={"email": "fail@example.com", "code": "999999"}
    )

    process_outbox()

    event.refresh_from_db()

    assert event.status == OutboxStatus.pending
    assert event.retry_count == 1
    assert "smtp down" in event.last_error