# tests/concurrency/test_double_payment.py
import pytest

from tests.concurrency.base import ConcurrentRunner

from payment.services.verify import (
    verify_payment,
)


pytestmark = pytest.mark.django_db(
    transaction=True,
)


def test_verify_is_safe(successful_payment):

    runner = ConcurrentRunner()

    runner.run(

        lambda: verify_payment(
            authority=successful_payment.authority_id,
            ref_id="1",
        ),

        lambda: verify_payment(
            authority=successful_payment.authority_id,
            ref_id="2",
        ),
    )

    successful_payment.refresh_from_db()

    assert successful_payment.is_consumed
