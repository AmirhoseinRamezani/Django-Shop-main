# tests/concurrency/test_idempotency.py
import pytest

from django.core.exceptions import ValidationError

from payment.services.verify import verify_payment

pytestmark = pytest.mark.django_db


def test_verify_twice_returns_same_payment(
    payment,
):

    payment1 = verify_payment(
            authority=payment.authority_id,
            ref_id=111,
        )

    payment2 = verify_payment(
                authority=payment.authority_id,
                ref_id=112,
            )
    
    assert payment1.pk == payment2.pk
    
    # with pytest.raises(ValidationError):

    #     verify_payment(
    #         authority=payment.authority_id,
    #         ref_id=112,
    #     )