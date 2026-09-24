# core/tests/services/payment/test_reconciliation.py
from unittest.mock import patch

import pytest

from tests.base import BaseTestCase
from tests.factories.payment import PaymentAttemptFactory

from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType
from payment.exceptions import PaymentGatewayError, PaymentInvariantViolation
from payment.providers.base import GatewayInquiryResult
from payment.repositories.payment_attempt_repository import PaymentAttemptRepository
from payment.services.reconciliation import PaymentReconciliationService

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]


class TestPaymentReconciliationService(BaseTestCase):
    def _pending_payment(self, payment_factory):
        payment = payment_factory()
        attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-RECON",
        )
        return payment, attempt

    def _inquiry(self, payment, **overrides):
        values = {
            "success": True,
            "gateway": PaymentGateway.ZARINPAL,
            "gateway_reference": "REF-RECON",
            "gateway_transaction_id": "TX-RECON",
            "response_code": "100",
            "message": "inquired",
            "amount": payment.amount,
            "currency": payment.currency,
        }
        values.update(overrides)
        return GatewayInquiryResult(**values)

    def test_successful_inquiry_settles_exact_attempt_and_consumes_payment(
        self,
        payment_factory,
    ):
        payment, attempt = self._pending_payment(payment_factory)

        with patch(
            "payment.services.reconciliation.GatewayService.inquire",
            return_value=self._inquiry(payment),
        ) as mock_inquire:
            result = PaymentReconciliationService.reconcile_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
            )

        mock_inquire.assert_called_once()
        payment.refresh_from_db()
        attempt.refresh_from_db()
        payment.order.refresh_from_db()

        assert result.pk == payment.pk
        assert payment.status == PaymentStatusType.SUCCESS
        assert payment.is_consumed is True
        assert attempt.status == PaymentAttemptStatus.SUCCESS
        assert attempt.gateway_reference == "REF-RECON"
        assert attempt.gateway_transaction_id == "TX-RECON"
        assert payment.order.is_paid

    def test_negative_inquiry_keeps_payment_and_attempt_pending(
        self,
        payment_factory,
    ):
        payment, attempt = self._pending_payment(payment_factory)

        with patch(
            "payment.services.reconciliation.GatewayService.inquire",
            return_value=self._inquiry(
                payment,
                success=False,
                gateway_reference=None,
                gateway_transaction_id=None,
                response_code="-1",
                message="not confirmed",
            ),
        ):
            result = PaymentReconciliationService.reconcile_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
            )

        payment.refresh_from_db()
        attempt.refresh_from_db()

        assert result.status == PaymentStatusType.PENDING
        assert payment.status == PaymentStatusType.PENDING
        assert payment.is_consumed is False
        assert attempt.status == PaymentAttemptStatus.PENDING

    def test_inquiry_transport_failure_keeps_local_state_unresolved(
        self,
        payment_factory,
    ):
        payment, attempt = self._pending_payment(payment_factory)

        with patch(
            "payment.services.reconciliation.GatewayService.inquire",
            side_effect=PaymentGatewayError(
                "Gateway unavailable",
                retryable=True,
            ),
        ):
            with pytest.raises(PaymentGatewayError):
                PaymentReconciliationService.reconcile_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                )

        payment.refresh_from_db()
        attempt.refresh_from_db()
        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING

    def test_successful_inquiry_without_reference_is_rejected(
        self,
        payment_factory,
    ):
        payment, attempt = self._pending_payment(payment_factory)

        with patch(
            "payment.services.reconciliation.GatewayService.inquire",
            return_value=self._inquiry(
                payment,
                gateway_reference=None,
            ),
        ):
            with pytest.raises(PaymentInvariantViolation):
                PaymentReconciliationService.reconcile_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                )

        payment.refresh_from_db()
        attempt.refresh_from_db()
        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING

    def test_late_inquiry_cannot_resurrect_old_attempt(
        self,
        payment_factory,
    ):
        payment, first = self._pending_payment(payment_factory)
        first.mark_failed(reason="timeout", response_code="-1")
        PaymentAttemptRepository.save_failure(first)

        second = PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-RETRY",
            retry_of=first,
            retry_count=2,
        )

        with patch(
            "payment.services.reconciliation.GatewayService.inquire",
            return_value=self._inquiry(payment),
        ):
            with pytest.raises(PaymentInvariantViolation):
                PaymentReconciliationService.reconcile_payment(
                    payment_id=payment.pk,
                    attempt_id=first.pk,
                )

        payment.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()

        assert payment.status == PaymentStatusType.PENDING
        assert first.status == PaymentAttemptStatus.FAILED
        assert second.status == PaymentAttemptStatus.PENDING
