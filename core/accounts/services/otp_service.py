# accounts/services/otp_service.py
import secrets
from datetime import timedelta

from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

from accounts.models import EmailOTP, OTPPurpose
from events.models.outbox import OutboxEvent


User = get_user_model()


OTP_EXPIRE_MINUTES = 2
OTP_MIN_INTERVAL_SECONDS = 60
OTP_MAX_PER_10_MIN = 5


def _generate_code() -> str:
    """
    Generate a cryptographically secure 4-digit OTP.
    """
    return f"{secrets.randbelow(10000):04}"


def _rate_limit_check(email: str):
    now = timezone.now()

    last_otp = (
        EmailOTP.objects
        .filter(email=email)
        .order_by("-created_date")
        .first()
    )

    if last_otp and (now - last_otp.created_date).total_seconds() < OTP_MIN_INTERVAL_SECONDS:
        raise ValidationError("لطفاً کمی صبر کنید")

    last_10_min = now - timedelta(minutes=10)
    
    count = EmailOTP.objects.filter(
        email=email,
        created_date__gte=last_10_min
    ).count()

    if count >= OTP_MAX_PER_10_MIN:
        raise ValidationError("تعداد درخواست بیش از حد مجاز")


def generate_or_reuse_otp(*, email: str, purpose=OTPPurpose.SIGNUP) -> EmailOTP:
    now = timezone.now()

    existing = EmailOTP.objects.filter(
        email=email,
        purpose=purpose,
        is_consumed=False,
        expire_at__gt=now
    ).first()

    if existing:
        otp = existing
    else:
        _rate_limit_check(email)

        raw_code = _generate_code()
        
        otp = EmailOTP.objects.create(
            email=email,
            purpose=purpose,
            code_hash=make_password(raw_code),
            expire_at=now + timedelta(minutes=OTP_EXPIRE_MINUTES),
        )

        OutboxEvent.objects.create(
            topic="user.otp",
            payload={
                "email": otp.email,
                "code": raw_code,
                "purpose": otp.purpose,
            }
        )

        return otp


def verify_otp(*, email: str, code: str, purpose=OTPPurpose.SIGNUP):
    otp = EmailOTP.objects.filter(
        email=email,
        purpose=purpose,
        is_consumed=False,
    ).order_by("-created_date").first()

    if not otp:
        raise ValidationError("کد نامعتبر یا منقضی شده")

    otp.verify(code)

    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "is_active": True,
            "is_verified": True,
        }
    )

    if not created and not user.is_verified:
        user.is_verified = True
        user.save(update_fields=["is_verified"])

    return user