# tests/fixtures/coupons.py
import pytest

from order.models import CouponModel


@pytest.fixture
def used_coupon(coupon):

    coupon.used_count = coupon.max_usage
    coupon.save(
        update_fields=[
            "used_count",
        ]
    )

    return coupon
    
from tests.factories.shop import (
    CouponFactory,
)

@pytest.fixture
def coupon(db):
    return CouponFactory()


@pytest.fixture
def expired_coupon(db):
    return CouponFactory(expired=True)
