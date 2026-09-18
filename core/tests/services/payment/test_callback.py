# core/tests/services/payment/test_callback.py
import pytest
from unittest.mock import patch

from payment.enums import PaymentAttemptStatus, PaymentGateway
from payment.providers.base import GatewayCallback
from payment.exceptions import (
    PaymentCallbackIdentityMismatchError,
    PaymentCallbackMissingIdentityError,
    PaymentInvalidCallbackError,
)
from payment.services.callback import (
    resolve_callback,
    resolve_payment_id,
    verify_callback,
)
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
            status=PaymentAttemptStatus.TIMEOUT,
            authority_id="AUTH-CALLBACK-OLD",
            failure_reason="Gateway timeout",
            latency_ms=5000,
        )
        second_attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-CALLBACK-CURRENT",
            retry_of=first_attempt,
            retry_count=2,
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

    def test_callback_verification_preserves_exact_attempt_identity(
        self,
        payment_factory,
        monkeypatch,
    ):
        payment = payment_factory()

        first_attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.TIMEOUT,
            authority_id="AUTH-CALLBACK-OLD",
            failure_reason="Gateway timeout",
            latency_ms=5000,
        )
        second_attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-CALLBACK-CURRENT",
            retry_of=first_attempt,
            retry_count=2,
        )

        calls = {}

        def fake_verify_payment(**kwargs):
            calls.update(kwargs)
            return payment

        monkeypatch.setattr(
            "payment.services.callback.verify_payment",
            fake_verify_payment,
        )

        result = verify_callback(
            callback=GatewayCallback(
                gateway=PaymentGateway.ZARINPAL,
                authority="AUTH-CALLBACK-CURRENT",
            ),
        )

        assert result is payment
        assert calls["payment_id"] == payment.pk
        assert calls["attempt_id"] == second_attempt.pk
        assert calls["ref_id"] is None
        assert calls["response"] == {}


    def test_callback_status_cannot_force_verification_failure(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-CALLBACK-STATUS",
        )

        with patch(
            "payment.services.callback.verify_payment",
            return_value=payment,
        ) as mock_verify:
            result = verify_callback(
                callback=GatewayCallback(
                    gateway=PaymentGateway.ZARINPAL,
                    authority=attempt.authority_id,
                    success=False,
                    response_code="NOK",
                    message="Client-controlled failure status",
                ),
            )

        assert result is payment
        mock_verify.assert_called_once_with(
            payment_id=payment.pk,
            attempt_id=attempt.pk,
            ref_id=None,
            response={},
        )

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
