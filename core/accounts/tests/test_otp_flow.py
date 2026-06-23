# accounts/tests/test_otp_flow.py
import pytest
from django.urls import reverse
from django.core import mail
from accounts.models import EmailOTP
from events.models import OutboxEvent, OutboxStatus

@pytest.mark.django_db
def test_request_otp_creates_emailotp_and_outbox(client, email):
    url = reverse("accounts-api:otp-request")
    response = client.post(url, {"email": email,"purpose": "login"})

    assert response.status_code == 200
    assert EmailOTP.objects.filter(email=email).exists()
    assert OutboxEvent.objects.filter(topic="user.otp").exists()

@pytest.mark.django_db
def test_process_outbox_sends_email_and_updates_status(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    event = OutboxEvent.objects.create(
        topic="user.otp",
        payload={"email": "user@example.com", "code": "123456"}
    )

    from events.services.processor import process_outbox
    process_outbox()

    event.refresh_from_db()

    assert event.status == OutboxStatus.processed
    assert len(mail.outbox) == 1
    assert "123456" in mail.outbox[0].body
