# core/tests/services/payment/test_verify_payment.py
from unittest.mock import patch

import pytest

from tests.base import BaseTestCase
from tests.factories.payment import PaymentAttemptFactory

from order.models import OrderStatusType

from payment.enums import (
    PaymentAttemptStatus,
    PaymentGateway,
    PaymentStatusType,
)
from payment.exceptions import PaymentGatewayError, PaymentInvariantViolation
from payment.providers.base import GatewayVerificationResult
from payment.repositories.payment_attempt_repository import PaymentAttemptRepository
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
    def _result(
        payment,
        **overrides,
    ):
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

    def _payment_with_attempt(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-VERIFY",
        )

        return payment, attempt

    def test_success_verify(
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

        self.assert_payment_success(payment)
        self.assert_order_paid(payment.order)

    def test_verify_twice_is_idempotent(
        self,
        payment_factory,
    ):
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

        first = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-OLD",
        )
        second = PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            status=PaymentAttemptStatus.FAILED,
            authority_id="AUTH-NEW",
        )

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self.verification_result(payment),
        ) as mock_verify:
            verify_payment(
                payment_id=payment.pk,
                attempt_id=first.pk,
                ref_id="REF-TEST",
                response={"status": "ok"},
            )

        mock_verify.assert_called_once()
        called_context = mock_verify.call_args.kwargs
        assert called_context["attempt"].attempt_id == first.pk
        assert called_context["attempt"].attempt_number == 1
        assert second.pk != first.pk

    def test_late_callback_cannot_switch_to_newer_attempt(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        first = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.TIMEOUT,
            authority_id="AUTH-TIMEOUT",
            gateway_reference="",
        )
        second = PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-RETRY",
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
        second.refresh_from_db()
        assert second.status == PaymentAttemptStatus.PENDING

    def test_conflicting_gateway_reference_is_rejected(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(payment_factory)

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
        payment, attempt = self._payment_with_attempt(payment_factory)

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

    def test_success_without_gateway_reference_is_rejected(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(payment_factory)

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
        payment, attempt = self._payment_with_attempt(payment_factory)

        attempt.mark_success(
            authority_id=attempt.authority_id,
            gateway_reference="REF-TEST",
        )
        PaymentAttemptRepository.save_success(attempt)

        payment.succeed()
        PaymentRepository.save(payment, update_fields=("status",))

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

    def test_duplicate_terminal_callback_with_conflicting_ref_is_rejected(
        self,
        payment_factory,
    ):
        payment, attempt = self._payment_with_attempt(payment_factory)

        attempt.mark_success(
            authority_id=attempt.authority_id,
            gateway_reference="REF-TEST",
        )
        PaymentAttemptRepository.save_success(attempt)

        payment.succeed()
        PaymentRepository.save(
            payment,
            update_fields=("status",),
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
        payment, attempt = self._payment_with_attempt(payment_factory)

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
        payment, attempt = self._payment_with_attempt(payment_factory)

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
        payment, attempt = self._payment_with_attempt(payment_factory)

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
