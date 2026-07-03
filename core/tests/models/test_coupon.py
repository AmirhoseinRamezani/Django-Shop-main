# tests/models/test_coupon.py
import pytest

from django.utils import timezone
from datetime import timedelta


pytestmark = pytest.mark.django_db


class TestCouponModel:

    def test_coupon_is_valid(self, coupon):

        assert coupon.is_valid() is True

    def test_inactive_coupon_is_invalid(self, coupon):

        coupon.is_active = False

        assert coupon.is_valid() is False

    def test_expired_coupon_is_invalid(self, coupon):

        coupon.expiration_date = timezone.now() - timedelta(days=1)

        assert coupon.is_valid() is False

    def test_usage_limit_coupon_is_invalid(self, coupon):

        coupon.used_count = coupon.max_limit_usage

        assert coupon.is_valid() is False

    def test_mark_used(self, coupon):

        coupon.mark_used()

        coupon.refresh_from_db()

        assert coupon.used_count == 1

    def test_rollback(self, coupon):

        coupon.used_count = 1
        coupon.save()

        coupon.rollback()

        coupon.refresh_from_db()

        assert coupon.used_count == 0

    def test_rollback_never_negative(self, coupon):

        coupon.rollback()

        coupon.refresh_from_db()

        assert coupon.used_count == 0