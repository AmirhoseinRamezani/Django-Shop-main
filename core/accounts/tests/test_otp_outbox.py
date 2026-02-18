# accounts/test/test_otp_outbox.py
import pytest

from accounts.models import EmailOTP
from accounts.models import OTPPurpose
from accounts.models import User
from events.models import OutboxEvent, OutboxStatus
from django.contrib.auth.hashers import make_password


@pytest.mark.django_db
def test_otp_creates_outbox_event():
    # Creating OTP must create a pending outbox event

    otp = EmailOTP.objects.create(
        email="user@test.com",
        code="123456",
    )

    event = OutboxEvent.objects.get(topic="user.otp")

    assert event.status == OutboxStatus.pending
    assert event.payload["email"] == otp.email
    assert event.payload["code"] == otp.code

@property
def code(self):
    return None  # raw code is never stored after hashing