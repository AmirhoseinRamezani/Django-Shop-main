# tests/e2e/test_payment_retry.py
import pytest

from django.core.exceptions import ValidationError

from payment.services.verify import verify_payment


pytestmark = pytest.mark.django_db


class TestPaymentRetry:

    def test_verify_twice_returns_same_payment(
        self,
        payment,
    ):
        verify_payment(
            authority=payment.authority_id,
            ref_id=11,
            response={},
        )

        with pytest.raises(ValidationError):

            verify_payment(
                authority=payment.authority_id,
                ref_id=11,
                response={},
            )
