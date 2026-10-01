# tests/builders/coupon_builder.py
from django.utils import timezone
from datetime import timedelta

from tests.factories.shop import CouponFactory

class CouponBuilder:

    def __init__(self):

        self.kwargs = {}

    # ------------------------

    def expired(self):

        self.kwargs["expiration_date"] = (
            timezone.now() - timedelta(days=1)
        )

        return self

    # ------------------------

    def inactive(self):

        self.kwargs["is_active"] = False

        return self

    # ------------------------

    def exhausted(self):

        self.kwargs["used_count"] = 10
        self.kwargs["max_limit_usage"] = 10

        return self

    # ------------------------

    def percent(self, value):

        self.kwargs["discount_percent"] = value

        return self

    # ------------------------

    def build(self):

        return CouponFactory(**self.kwargs)
