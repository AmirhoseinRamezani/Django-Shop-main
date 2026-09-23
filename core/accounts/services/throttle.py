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
    # Missing client IP must not bypass the throttle. Use a dedicated bucket
    # rather than trusting an absent/forged address.
    ip = ip or "unknown"
    key = _key(ip, email)

    # cache.add is atomic on the supported production cache backends and
    # establishes the first counter without a check-then-set race.
    if cache.add(key, 1, timeout=window):
        return

    try:
        count = cache.incr(key)
    except ValueError:
        # The key may have expired between add/incr. Re-establish it atomically.
        if cache.add(key, 1, timeout=window):
            return
        count = cache.incr(key)

    if count > limit:
        # Undo this caller's reservation. incr/decr are atomic operations on
        # Redis and compatible Django cache backends.
        cache.decr(key)
        raise OTPThrottleException()
