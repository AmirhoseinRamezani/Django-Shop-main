# tests/performance/test_payment_queries.py
import pytest

from tests.helpers.queries import (
    assert_max_queries,
)

from payment.services.verify import (
    verify_payment,
)


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.performance,
]


class TestVerifyQueries:

    def test_verify_payment_queries(
        self,
        payment,
        mocker,
    ):
        mocker.patch(
            "payment.services.verify.confirm_order_payment",
        )

        assert_max_queries(
            5,
            verify_payment,
            authority=payment.authority_id,
            ref_id=123456,
            response={},
        )