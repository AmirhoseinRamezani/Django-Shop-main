# accounts/tests/services/test_otp_service.py
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta

from accounts.services.otp_service import (
    generate_or_reuse_otp,
    verify_otp,
)
from accounts.models import EmailOTP, OTPPurpose
from events.models import OutboxEvent


@pytest.mark.django_db
def test_generate_otp_creates_emailotp_and_outbox(email):
    otp = generate_or_reuse_otp(
        email=email,
        purpose=OTPPurpose.LOGIN,
    )

    assert EmailOTP.objects.count() == 1
    assert OutboxEvent.objects.count() == 1
    assert otp.is_consumed is False
    assert otp.expire_at > timezone.now()


@pytest.mark.django_db
def test_generate_otp_reuses_existing(email):
    otp1 = generate_or_reuse_otp(
        email=email,
        purpose=OTPPurpose.LOGIN,
    )
    otp2 = generate_or_reuse_otp(
        email=email,
        purpose=OTPPurpose.LOGIN,
    )

    assert otp1.id == otp2.id
    assert EmailOTP.objects.count() == 1


@pytest.mark.django_db
def test_verify_otp_consumes_code(email):
    otp = generate_or_reuse_otp(
        email=email,
        purpose=OTPPurpose.LOGIN,
    )

    # simulate user-entered correct code via outbox
    event = OutboxEvent.objects.get(topic="user.otp")
    code = event.payload["code"]

    verify_otp(
        email=email,
        code=code,
        purpose=OTPPurpose.LOGIN,
    )

    otp.refresh_from_db()
    assert otp.is_consumed is True


@pytest.mark.django_db
def test_expired_otp_is_rejected(email):
    otp = generate_or_reuse_otp(
        email=email,
        purpose=OTPPurpose.LOGIN,
    )
    otp.expire_at = timezone.now() - timedelta(seconds=1)
    otp.save(update_fields=["expire_at"])

    event = OutboxEvent.objects.get(topic="user.otp")
    code = event.payload["code"]

    with pytest.raises(Exception):
        verify_otp(
            email=email,
            code=code,
            purpose=OTPPurpose.LOGIN,
        )


@pytest.mark.django_db(transaction=True)
def test_concurrent_otp_verification_consumes_once(email):
    from tests.concurrency.base import ConcurrentRunner

    otp = generate_or_reuse_otp(
        email=email,
        purpose=OTPPurpose.LOGIN,
    )
    code = OutboxEvent.objects.get(topic="user.otp").payload["code"]

    successes = []
    failures = []

    def verify():
        try:
            verify_otp(
                email=email,
                code=code,
                purpose=OTPPurpose.LOGIN,
            )
            successes.append(True)
        except ValidationError as exc:
            failures.append(exc)

    ConcurrentRunner().run(verify, verify)

    otp.refresh_from_db()
    assert len(successes) == 1
    assert len(failures) == 1
    assert otp.is_consumed is True
    assert otp.attempts == 0
