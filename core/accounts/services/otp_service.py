# accounts/services/otp_service.py
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

from accounts.models import EmailOTP, OTPPurpose
from events.models.outbox import OutboxEvent
from accounts.services.throttle import check_and_increment_otp_throttle

User = get_user_model()

OTP_EXPIRE_MINUTES = 2
OTP_MIN_INTERVAL_SECONDS = 60
OTP_MAX_PER_10_MIN = 5

@transaction.atomic
def generate_or_reuse_otp(
    *,
    email: str,
    purpose: OTPPurpose,
    request=None,
) -> EmailOTP:
    """
    Generates a new OTP or reuses a valid existing one.

    Rules:
    - Throttle per (ip, email)
    - Reuse unexpired & unconsumed OTP
    - Enforce time & volume limits
    - Emit outbox event for async delivery
    """

    # --- Throttle (edge-safe: fail-open on missing IP)
    ip = getattr(request, "ip_address", None)
    check_and_increment_otp_throttle(ip=ip, email=email)

    now = timezone.now()

    # --- Reuse existing valid OTP (important for idempotency)
    existing =(
        EmailOTP.objects
        .select_for_update()
        .filter(
            email=email,
            purpose=purpose,
            is_consumed=False,
            expire_at__gt=timezone.now(),
        )
        .order_by("-created_date")
        .first()
    )

    if existing:
        return existing

    # --- Business rate limits (time + volume)
    _rate_limit_check(email)

    # --- Generate secure random code
    raw_code = _generate_code()

    # --- Persist OTP (hashed)
    otp = EmailOTP.objects.create(
        email=email,
        purpose=purpose,
        code_hash=make_password(raw_code),
        expire_at=now + timedelta(minutes=OTP_EXPIRE_MINUTES),
    )
    # --- Outbox event (async email/SMS delivery)
    OutboxEvent.objects.create(
        topic="user.otp",
        payload={
            "email": otp.email,
            "code": raw_code,
            "purpose": otp.purpose,
        },
    )

    return otp

def verify_otp(*, email: str, code: str, purpose: OTPPurpose) -> None:
    otp = _get_valid_otp(email=email, purpose=purpose)
    otp.verify(code)


def verify_login_otp(*, email: str, code: str):
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        raise ValidationError("کاربری با این ایمیل یافت نشد")

    verify_otp(email=email, code=code, purpose=OTPPurpose.LOGIN)

    if not user.is_verified:
        user.is_verified = True
        user.save(update_fields=["is_verified"])

    return user


def _generate_code() -> str:
    return f"{secrets.randbelow(10000):04}"


def _rate_limit_check(email: str) -> None:
    now = timezone.now()

    last_otp = (
        EmailOTP.objects
        .filter(email=email)
        .order_by("-created_date")
        .first()
    )

    if last_otp:
        delta = (now - last_otp.created_date).total_seconds()
        if delta < OTP_MIN_INTERVAL_SECONDS:
            raise ValidationError("لطفاً کمی صبر کنید")

    last_10_min = now - timedelta(minutes=10)
    count = EmailOTP.objects.filter(
        email=email,
        created_date__gte=last_10_min,
    ).count()

    if count >= OTP_MAX_PER_10_MIN:
        raise ValidationError("تعداد درخواست بیش از حد مجاز")


def _get_valid_otp(*, email: str, purpose: OTPPurpose) -> EmailOTP:
    otp = (
        EmailOTP.objects
        .filter(
            email=email,
            purpose=purpose,
            is_consumed=False,
            expire_at__gt=timezone.now(),
        )
        .order_by("-created_date")
        .first()
    )

    if not otp:
        raise ValidationError("کد نامعتبر یا منقضی شده")

    return otp
