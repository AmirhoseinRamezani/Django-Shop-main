# core/tests/services/payment/test_callback.py
import pytest

from payment.exceptions import (
    PaymentCallbackIdentityMismatchError,
    PaymentCallbackMissingIdentityError,
    PaymentInvalidCallbackError,
)
from payment.services.callback import resolve_payment_id

from tests.factories.payment import PaymentAttemptFactory
from payment.enums import PaymentAttemptStatus

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]


class TestPaymentCallbackResolution:
    def test_resolves_payment_from_attempt_authority(self, payment_factory):
        payment = payment_factory()
        PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-CALLBACK-1",
        )

        assert resolve_payment_id(
            authority=" AUTH-CALLBACK-1 ",
        ) == payment.pk


    def test_ambiguous_authority_is_rejected(self, payment_factory):
        first = payment_factory()
        second = payment_factory()

        PaymentAttemptFactory(
            payment=first,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-DUPLICATE",
        )

        PaymentAttemptFactory(
            payment=second,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-DUPLICATE",
        )

        with pytest.raises(PaymentCallbackIdentityMismatchError):
            resolve_payment_id(
                authority="AUTH-DUPLICATE",
            )

    def test_unknown_authority_is_rejected(self):
        with pytest.raises(PaymentInvalidCallbackError):
            resolve_payment_id(authority="AUTH-UNKNOWN")
