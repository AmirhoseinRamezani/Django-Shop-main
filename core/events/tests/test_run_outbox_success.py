# events/tests/test_run_outbox_success.py

import pytest
from django.core import mail

from events.models import OutboxEvent, OutboxStatus
from events.services.processor import process_outbox


@pytest.mark.django_db
def test_run_outbox_success(settings):
    # Pending event must be processed and email sent

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    event = OutboxEvent.objects.create(
        topic="user.otp",
        payload={"email": "ok@test.com", "code": "111111"},
    )

    process_outbox()

    event.refresh_from_db()

    assert event.status == OutboxStatus.processed
    assert event.retry_count == 0
    assert len(mail.outbox) == 1
