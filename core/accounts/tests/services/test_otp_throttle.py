# accounts/tests/services/test_otp_throttle.py
import pytest
from django.core.cache import cache

from accounts.services.throttle import (
    check_and_increment_otp_throttle,
    OTPThrottleException,
)


@pytest.mark.django_db
def test_otp_throttle_blocks_after_limit():
    cache.clear()

    ip = "127.0.0.1"
    email = "throttle@test.com"

    for _ in range(5):
        check_and_increment_otp_throttle(ip=ip, email=email)

    with pytest.raises(OTPThrottleException):
        check_and_increment_otp_throttle(ip=ip, email=email)
