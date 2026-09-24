# core/tests/services/payment/test_verify_payment.py

from unittest.mock import patch
from datetime import timedelta

import pytest

from django.utils import timezone
from tests.base import BaseTestCase
from tests.factories.payment import PaymentAttemptFactory

from order.models import OrderStatusType

from payment.enums import (
    PaymentAttemptStatus,
    PaymentGateway,
    PaymentStatusType,
)
from payment.exceptions import (
    PaymentGatewayError,
    PaymentGatewayRejectedError,
    PaymentInvariantViolation,
)
from payment.providers.base import GatewayVerificationResult
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from payment.repositories.payment_repository import PaymentRepository
from payment.services.verify import verify_payment


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]


class TestVerifyPayment(BaseTestCase):

    @staticmethod
    def verification_result(payment):
        return GatewayVerificationResult(
            success=True,
            gateway=PaymentGateway.ZARINPAL,
            gateway_reference="REF-TEST",
            gateway_transaction_id="123456",
            response_code="100",
            message="verified",
            amount=payment.amount,
            currency=payment.currency,
        )

    @staticmethod
    def _result(payment, **overrides):
        values = {
            "success": True,
            "gateway": PaymentGateway.ZARINPAL,
            "gateway_reference": "REF-TEST",
            "gateway_transaction_id": "123456",
            "response_code": "100",
            "message": "verified",
            "amount": payment.amount,
            "currency": payment.currency,
        }
        values.update(overrides)
        return GatewayVerificationResult(**values)

    def _payment_with_attempt(self, payment_factory):
        payment = payment_factory()

        attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-VERIFY",
        )

        return payment, attempt

    def _failed_first_attempt(self, payment):
        attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-OLD",
        )

        # Make terminal-transition timing deterministic. The model invariant
        # requires finished_at >= started_at; explicit past time avoids
        # dependence on wall-clock ordering between ORM save and transition.
        attempt.started_at = timezone.now() - timedelta(seconds=1)
 
        attempt.mark_failed(
            reason="Gateway payment failed",
            response_code="-1",
        )

        PaymentAttemptRepository.save_failure(attempt)

        return attempt

    def _timeout_first_attempt(self, payment):
        attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-TIMEOUT",
        )

        attempt.mark_timeout(
            reason="Gateway timeout",
            latency_ms=5000,
        )

        PaymentAttemptRepository.save_failure(attempt)

        return attempt

    def test_success_verify(self, payment_factory):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self.verification_result(payment),
        ):
            verify_payment(
                payment_id=payment.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

        self.assert_payment_success(payment)
        self.assert_order_paid(payment.order)

    def test_verify_twice_is_idempotent(self, payment_factory):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self.verification_result(payment),
        ) as mock_verify:
            verify_payment(
                payment_id=payment.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

            verify_payment(
                payment_id=payment.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

        assert mock_verify.call_count == 1

        payment.refresh_from_db()

        assert payment.status == PaymentStatusType.SUCCESS

    def test_verification_is_bound_to_exact_attempt(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        first = self._failed_first_attempt(payment)

        second = PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-NEW",
            retry_of=first,
            retry_count=2,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self.verification_result(payment),
        ) as mock_verify:
            verify_payment(
                payment_id=payment.pk,
                attempt_id=second.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

        mock_verify.assert_called_once()

        called_context = mock_verify.call_args.kwargs

        assert called_context["attempt"].attempt_id == second.pk
        assert called_context["attempt"].attempt_number == 2
        assert called_context["attempt"].payment_id == payment.pk
        assert first.pk != second.pk
        
    def test_transport_failure_keeps_payment_and_attempt_pending(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(payment_factory)

        with patch(
            "payment.services.verify.GatewayService.verify",
            side_effect=PaymentGatewayError(
                "Gateway unavailable",
                retryable=True,
            ),
        ) as mock_verify:
            with pytest.raises(PaymentGatewayError) as exc_info:
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                    ref_id="REF-TEST",
                )

        mock_verify.assert_called_once()

        payment.refresh_from_db()
        attempt.refresh_from_db()

        assert exc_info.value.retryable is True
        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert payment.is_consumed is False
        assert attempt.gateway_reference == ""
        assert attempt.gateway_transaction_id == ""

    def test_late_callback_cannot_switch_to_newer_attempt(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        first = self._timeout_first_attempt(payment)

        second = PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-RETRY",
            retry_of=first,
            retry_count=2,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
        ) as mock_verify:
            with pytest.raises(PaymentInvariantViolation):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=first.pk,
                    ref_id="REF-TIMEOUT",
                    response={"status": "OK"},
                )

        mock_verify.assert_not_called()

        first.refresh_from_db()
        second.refresh_from_db()

        assert first.status == PaymentAttemptStatus.TIMEOUT
        assert second.status == PaymentAttemptStatus.PENDING

    def test_conflicting_gateway_reference_is_rejected(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self._result(
                payment,
                gateway_reference="REF-CONFLICT",
            ),
        ):
            with pytest.raises(PaymentInvariantViolation):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                    ref_id="REF-TEST",
                )

        payment.refresh_from_db()
        attempt.refresh_from_db()

        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert attempt.gateway_reference == ""

    def test_gateway_amount_mismatch_is_rejected(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self._result(
                payment,
                amount=payment.amount + 1,
            ),
        ):
            with pytest.raises(PaymentInvariantViolation):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                    ref_id="REF-TEST",
                )

        payment.refresh_from_db()

        assert payment.status == PaymentStatusType.PENDING

    def test_explicit_gateway_rejection_finalizes_payment_as_failed(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        rejection = self._result(
            payment,
            success=False,
            gateway_reference="REF-REJECTED",
            gateway_transaction_id=None,
            response_code="-21",
            message="Payment rejected",
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=rejection,
        ):
            with pytest.raises(PaymentGatewayRejectedError) as exc_info:
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                    ref_id="REF-REJECTED",
                )

        assert exc_info.value.retryable is False

        payment.refresh_from_db()
        attempt.refresh_from_db()

        assert payment.status == PaymentStatusType.FAILED
        assert payment.is_consumed is False
        assert attempt.status == PaymentAttemptStatus.FAILED
        assert attempt.gateway_reference == ""
        assert attempt.response_code == "-21"
        assert attempt.failure_reason == "Payment rejected"

    def test_rejected_result_with_mismatched_amount_does_not_finalize_payment(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        rejection = self._result(
            payment,
            success=False,
            amount=payment.amount + 1,
            gateway_reference="REF-REJECTED",
            response_code="-21",
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=rejection,
        ):
            with pytest.raises(PaymentInvariantViolation):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                    ref_id="REF-REJECTED",
                )

        payment.refresh_from_db()
        attempt.refresh_from_db()

        assert payment.status == PaymentStatusType.PENDING
        assert payment.is_consumed is False
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert attempt.gateway_reference == ""

    def test_success_without_gateway_reference_is_rejected(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self._result(
                payment,
                gateway_reference=None,
            ),
        ):
            with pytest.raises(PaymentGatewayError):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                    ref_id="REF-CLIENT-CONTROLLED",
                )

        payment.refresh_from_db()
        attempt.refresh_from_db()

        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING

    def test_callback_reference_cannot_become_gateway_evidence(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self._result(
                payment,
                gateway_reference=None,
            ),
        ):
            with pytest.raises(PaymentGatewayError):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                    ref_id="REF-CLIENT-CONTROLLED",
                )

        payment.refresh_from_db()
        attempt.refresh_from_db()

        assert payment.status == PaymentStatusType.PENDING
        assert payment.is_consumed is False
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert attempt.gateway_reference == ""

    def test_failed_payment_cannot_verify(
        self,
        payment_factory,
    ):
        payment = payment_factory(
            failed=True,
        )

        with pytest.raises(PaymentInvariantViolation):
            verify_payment(
                payment_id=payment.pk,
                ref_id="REF-TEST",
                response={},
            )

    def test_already_finalized_payment_still_runs_consumption_path(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        attempt.mark_success(
            authority_id=attempt.authority_id,
            gateway_reference="REF-TEST",
        )

        PaymentAttemptRepository.save_success(
            attempt,
        )

        payment.succeed()

        PaymentRepository.save(
            payment,
            update_fields=(
                "status",
            ),
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
        ) as mock_verify:
            result = verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

        mock_verify.assert_not_called()

        assert result.is_consumed is True

    def test_successful_payment_without_successful_attempt_is_rejected(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        payment.succeed()

        PaymentRepository.save(
            payment,
            update_fields=(
                "status",
            ),
        )

        with pytest.raises(PaymentInvariantViolation):
            verify_payment(
                payment_id=payment.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

        payment.refresh_from_db()

        assert payment.is_consumed is False

    def test_duplicate_terminal_callback_with_conflicting_ref_is_rejected(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        attempt.mark_success(
            authority_id=attempt.authority_id,
            gateway_reference="REF-TEST",
        )

        PaymentAttemptRepository.save_success(
            attempt,
        )

        payment.succeed()

        PaymentRepository.save(
            payment,
            update_fields=(
                "status",
            ),
        )

        with pytest.raises(PaymentInvariantViolation):
            verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
                ref_id="REF-CONFLICT",
                response={"status": "ok"},
            )

        payment.refresh_from_db()

        assert payment.is_consumed is False

    def test_payment_consumed(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self.verification_result(payment),
        ):
            verify_payment(
                payment_id=payment.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

        payment.refresh_from_db()

        assert payment.is_consumed is True

    def test_order_status_changed(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self.verification_result(payment),
        ):
            verify_payment(
                payment_id=payment.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

        payment.order.refresh_from_db()

        assert payment.order.status == OrderStatusType.paid
        assert payment.order.is_paid

    def test_ref_id_saved(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self.verification_result(payment),
        ):
            verify_payment(
                payment_id=payment.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

        attempt.refresh_from_db()

        assert attempt.gateway_reference == "REF-TEST"
        assert attempt.gateway_transaction_id == "123456"
        assert attempt.authority_id == "AUTH-VERIFY"
        assert attempt.status == PaymentAttemptStatus.SUCCESS

    def test_order_paid_date_is_set(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(
            payment_factory,
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self.verification_result(payment),
        ):
            verify_payment(
                payment_id=payment.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

        payment.order.refresh_from_db()

        assert payment.order.status == OrderStatusType.paid
        assert payment.order.paid_date is not None