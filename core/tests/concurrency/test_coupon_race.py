# tests/concurrency/test_coupon_race.py

import pytest

from tests.concurrency.base import (
    ConcurrentRunner,
)


pytestmark = pytest.mark.django_db(
    transaction=True,
)


def test_coupon_single_use(coupon):

    runner = ConcurrentRunner()

    runner.run(

        coupon.mark_used,

        coupon.mark_used,
    )

    coupon.refresh_from_db()

    assert coupon.used_count >= 1
