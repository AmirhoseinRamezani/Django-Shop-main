# accounts/tests/api/test_verify_otp.py
import pytest
from django.urls import reverse
from datetime import timedelta
from django.utils import timezone
from accounts.models import EmailOTP, OTPPurpose
from accounts.models.device_session import DeviceSession
from django.contrib.auth.hashers import make_password


@pytest.mark.django_db
def test_session_created_on_verify(client):
    email = "test@example.com"
    code = "123456"

    EmailOTP.objects.create(
        email=email,
        code_hash=make_password(code),
        purpose=OTPPurpose.LOGIN,
        expire_at=timezone.now() + timedelta(minutes=5),
    )

    response = client.post(
        reverse("accounts-api:otp-verify"),
        {
            "email": email,
            "code": code,
            "purpose": OTPPurpose.LOGIN,
        },
    )

    assert response.status_code == 200
    assert DeviceSession.objects.filter(user__email=email).exists()
