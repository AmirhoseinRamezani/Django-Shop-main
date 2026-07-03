import pytest

from order.models import CouponModel


@pytest.fixture
def coupon():

    return CouponModel.objects.create(

        code="OFF20",

        discount_percent=20,

        max_limit_usage=5,

        is_active=True,
    )