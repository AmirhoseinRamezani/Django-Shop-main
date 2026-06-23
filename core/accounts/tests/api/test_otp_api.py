# accounts/tests/api/test_otp_api.py
import pytest
from django.conf import settings
from django.core import mail


@pytest.mark.django_db
def test_request_otp_api_success(client, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    url = "/api/accounts/otp/request/"

    resp = client.post(url, {
        "email": "api@test.com",
        "purpose": "login",
    })

    assert resp.status_code == 200
