# accounts/tests/dispatchers/test_email_dispatcher.py
import pytest
from django.core import mail
from events.models import OutboxEvent
from events.services.dispatchers.email import send_email_event


@pytest.mark.django_db
def test_send_otp_email(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    event = OutboxEvent.objects.create(
        topic="user.otp",
        payload={"email": "user@example.com", "code": "654321"},
    )

    send_email_event(event)

    assert len(mail.outbox) == 1
    assert "654321" in mail.outbox[0].body
