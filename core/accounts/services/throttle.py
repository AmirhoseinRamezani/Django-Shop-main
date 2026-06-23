# accounts/services/throttle.py
from django.core.cache import cache
from rest_framework.exceptions import Throttled
from accounts.exceptions import OTPThrottleException

DEFAULT_LIMIT = 5
DEFAULT_WINDOW = 600  # seconds (10 min)


class OTPThrottleException(Throttled):
    default_detail = "Too many OTP requests. Please try later."
    default_code = "otp_throttled"

def _key(ip: str, email: str) -> str:
    return f"otp:throttle:{ip}:{email}"

def check_and_increment_otp_throttle(
    *,
    ip: str,
    email: str,
    limit: int = DEFAULT_LIMIT,
    window: int = DEFAULT_WINDOW,
):
    """
    Raises OTPThrottleException if limit exceeded.
    """
    if not ip:
        return  # fail-open (important for edge infra cases)

    key = _key(ip, email)

    count = cache.get(key, 0)

    if count >= limit:
        raise OTPThrottleException()

    if count == 0:
        cache.set(key, 1, timeout=window)
    else:
        cache.incr(key)
