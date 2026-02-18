# accounts/test/test_verify_otp.py
import pytest
from django.core.cache import cache
from django.urls import reverse
from accounts.models import User


@pytest.mark.django_db
def test_verify_otp_and_get_tokens(client):
    cache.clear()

    user = User.objects.create_user(
        email="verify@test.com",
        password="pass123"
    )

    cache.set("otp:verify@test.com", "123456", timeout=120)

    resp = client.post(
        "/api/accounts/otp/verify/",
        {
            "email": "verify@test.com",
            "code": "123456",
        },
    )

    assert resp.status_code == 200
    assert "access" in resp.json()
    assert "refresh" in resp.json()
