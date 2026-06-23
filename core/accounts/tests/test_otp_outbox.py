# accounts/test/test_otp_outbox.py
import pytest

from accounts.models import OTPPurpose
from accounts.models import User
from events.models import OutboxEvent, OutboxStatus
from accounts.services.otp_service import generate_or_reuse_otp

@pytest.mark.django_db
def test_otp_creates_outbox_event():
    # Creating OTP must create a pending outbox event

    generate_or_reuse_otp(
        email="user@test.com",
        purpose=OTPPurpose.LOGIN,
    )

    event = OutboxEvent.objects.get(topic="user.otp")

    assert event.status == OutboxStatus.pending
    assert event.payload["email"] == "user@test.com"
    assert "code" in event.payload
