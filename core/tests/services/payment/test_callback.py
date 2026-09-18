# core/tests/services/payment/test_callback.py
import pytest

from payment.enums import PaymentAttemptStatus, PaymentGateway
from payment.exceptions import (
    PaymentCallbackIdentityMismatchError,
    PaymentCallbackMissingIdentityError,
    PaymentInvalidCallbackError,
)
from payment.services.callback import resolve_callback, resolve_payment_id
from tests.factories.payment import PaymentAttemptFactory

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

    def test_resolves_exact_attempt_when_payment_has_multiple_attempts(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        first_attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-CALLBACK-OLD",
        )
        second_attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-CALLBACK-CURRENT",
        )

        first_resolution = resolve_callback(
            authority="AUTH-CALLBACK-OLD",
        )
        second_resolution = resolve_callback(
            authority="AUTH-CALLBACK-CURRENT",
        )

        assert first_resolution.payment_id == payment.pk
        assert first_resolution.attempt_id == first_attempt.pk
        assert second_resolution.payment_id == payment.pk
        assert second_resolution.attempt_id == second_attempt.pk
        assert first_resolution.attempt_id != second_resolution.attempt_id

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

    def test_missing_authority_is_rejected(self):
        with pytest.raises(PaymentCallbackMissingIdentityError):
            resolve_callback(authority="")

    def test_gateway_identity_is_returned(self, payment_factory):
        payment = payment_factory(
            gateway=PaymentGateway.ZARINPAL,
        )
        attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-GATEWAY-EXACT",
        )

        resolution = resolve_callback(
            authority="AUTH-GATEWAY-EXACT",
            gateway=PaymentGateway.ZARINPAL,
        )

        assert resolution.payment_id == payment.pk
        assert resolution.attempt_id == attempt.pk
        assert resolution.gateway == PaymentGateway.ZARINPAL
        assert resolution.authority == "AUTH-GATEWAY-EXACT"

    def test_gateway_mismatch_is_rejected(
        self,
        payment_factory,
    ):
        payment = payment_factory(
            gateway=PaymentGateway.ZARINPAL,
        )

        PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-GATEWAY-MISMATCH",
        )

        with pytest.raises(PaymentCallbackIdentityMismatchError):
            resolve_callback(
                authority="AUTH-GATEWAY-MISMATCH",
                gateway="stripe",
            )
