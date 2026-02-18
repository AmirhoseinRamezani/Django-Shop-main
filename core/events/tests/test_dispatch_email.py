# events/tests/test_dispatch_email.py
import pytest
from django.core import mail

from events.models.outbox import OutboxEvent
from events.services.dispatchers.email import send_email_event


@pytest.mark.django_db
def test_send_otp_email(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    event = OutboxEvent.objects.create(
        topic="user.otp",
        payload={
            "email": "user@example.com",
            "code": "123456",
        }
    )

    send_email_event(event)

    assert len(mail.outbox) == 1
    assert "123456" in mail.outbox[0].body