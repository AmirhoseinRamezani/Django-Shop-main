# tests/services/accounts/test_otp_service.py
import pytest

from django.core.exceptions import ValidationError

from accounts.models import (
    EmailOTP,
    OTPPurpose,
)

from accounts.services.otp_service import (
    generate_or_reuse_otp,
    verify_otp,
)

pytestmark = pytest.mark.django_db


class TestGenerateOTP:

    def test_create(self, email):

        otp = generate_or_reuse_otp(
            email=email,
            purpose=OTPPurpose.LOGIN,
        )

        assert isinstance(otp, EmailOTP)

    def test_reuse_existing(self, email):

        otp1 = generate_or_reuse_otp(
            email=email,
            purpose=OTPPurpose.LOGIN,
        )

        otp2 = generate_or_reuse_otp(
            email=email,
            purpose=OTPPurpose.LOGIN,
        )

        assert otp1.id == otp2.id

    def test_different_purpose(self, email, mocker):

        mocker.patch(
            "accounts.services.otp_service._rate_limit_check",
        )
        
        otp1 = generate_or_reuse_otp(
            email=email,
            purpose=OTPPurpose.LOGIN,
        )

        otp2 = generate_or_reuse_otp(
            email=email,
            purpose=OTPPurpose.SIGNUP,
        )

        assert otp1.id != otp2.id


class TestVerify:

    def test_invalid_code(self, email):

        otp = generate_or_reuse_otp(
            email=email,
            purpose=OTPPurpose.LOGIN,
        )

        with pytest.raises(ValidationError):

            verify_otp(
                email=email,
                code="0000",
                purpose=OTPPurpose.LOGIN,
            )

    def test_expired(self, email):

        otp = generate_or_reuse_otp(
            email=email,
            purpose=OTPPurpose.LOGIN,
        )

        from django.utils import timezone
        from datetime import timedelta

        otp.expire_at = timezone.now() - timedelta(seconds=1)
        otp.save(update_fields=["expire_at"])

        with pytest.raises(ValidationError):

            verify_otp(
                email=email,
                code="1111",
                purpose=OTPPurpose.LOGIN,
            )

    def test_wrong_email(self, email):

        generate_or_reuse_otp(
            email=email,
            purpose=OTPPurpose.LOGIN,
        )

        with pytest.raises(ValidationError):

            verify_otp(
                email="another@test.com",
                code="1234",
                purpose=OTPPurpose.LOGIN,
            )