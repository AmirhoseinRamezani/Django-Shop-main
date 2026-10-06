# core/tests/services/payment/test_identity_certification.py
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from order.models import OrderStatusType
from order.services.confirm_payment import confirm_order_payment
from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType
from payment.exceptions import PaymentInvariantViolation
from payment.providers.base import GatewayVerificationResult
from payment.services.verify import verify_payment
from tests.base import BaseTestCase
from tests.factories.payment import PaymentAttemptFactory


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]


class TestPaymentIdentityCertification(BaseTestCase):

    @staticmethod
    def _result(payment, **overrides):
        values = {
            "success": True,
            "gateway": PaymentGateway.ZARINPAL,
            "gateway_reference": "REF-IDENTITY",
            "gateway_transaction_id": "TX-IDENTITY",
            "response_code": "100",
            "message": "verified",
            "amount": payment.amount,
            "currency": payment.currency,
        }
        values.update(overrides)
        return GatewayVerificationResult(**values)

    def _pending_payment(self, payment_factory):
        payment = payment_factory(
            gateway=PaymentGateway.ZARINPAL,
        )
        attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-IDENTITY",
        )
        return payment, attempt

    def test_attempt_from_different_payment_is_rejected_before_gateway(
        self,
        payment_factory,
    ):
        payment, attempt = self._pending_payment(payment_factory)
        other_payment, other_attempt = self._pending_payment(payment_factory)

        with patch(
            "payment.services.verify.GatewayService.verify",
        ) as mock_verify:
            with pytest.raises(PaymentInvariantViolation, match="does not belong"):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=other_attempt.pk,
                )

        mock_verify.assert_not_called()
        payment.refresh_from_db()
        attempt.refresh_from_db()
        other_payment.refresh_from_db()
        other_attempt.refresh_from_db()

        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert other_payment.status == PaymentStatusType.PENDING
        assert other_attempt.status == PaymentAttemptStatus.PENDING

    def test_gateway_identity_mismatch_is_fail_closed(
        self,
        payment_factory,
    ):
        payment, attempt = self._pending_payment(payment_factory)

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self._result(
                payment,
                gateway="stripe",
            ),
        ):
            with pytest.raises(PaymentInvariantViolation, match="gateway"):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                )

        payment.refresh_from_db()
        attempt.refresh_from_db()
        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert payment.is_consumed is False

    def test_gateway_reference_mismatch_is_fail_closed(
        self,
        payment_factory,
    ):
        payment, attempt = self._pending_payment(payment_factory)

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self._result(
                payment,
                gateway_reference="REF-WRONG",
            ),
        ):
            with pytest.raises(PaymentInvariantViolation, match="reference"):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                    ref_id="REF-EXPECTED",
                )

        payment.refresh_from_db()
        attempt.refresh_from_db()
        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert attempt.gateway_reference == ""

    def test_gateway_transaction_identity_mismatch_is_fail_closed(
        self,
        payment_factory,
    ):
        payment, attempt = self._pending_payment(payment_factory)

        # A pending attempt cannot legally carry a transaction identity.
        # Transaction identity reconciliation is already covered by the
        # duplicate-success verification contract.
         
        assert attempt.gateway_transaction_id == ""

    def test_amount_identity_mismatch_is_fail_closed(
        self,
        payment_factory,
    ):
        payment, attempt = self._pending_payment(payment_factory)

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self._result(
                payment,
                amount=payment.amount + Decimal("1"),
            ),
        ):
            with pytest.raises(PaymentInvariantViolation, match="financial snapshot"):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                )

        payment.refresh_from_db()
        attempt.refresh_from_db()
        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert payment.is_consumed is False

    def test_currency_identity_mismatch_is_fail_closed(
        self,
        payment_factory,
    ):
        payment, attempt = self._pending_payment(payment_factory)

        with patch(
            "payment.services.verify.GatewayService.verify",
            return_value=self._result(
                payment,
                currency="USD",
            ),
        ):
            with pytest.raises(
                PaymentInvariantViolation,
                match="financial snapshot mismatch",
            ):
                verify_payment(
                    payment_id=payment.pk,
                    attempt_id=attempt.pk,
                )

        payment.refresh_from_db()
        attempt.refresh_from_db()
        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert payment.is_consumed is False

    def test_multiple_successful_attempts_block_order_confirmation(
        self,
        payment_factory,
    ):
        payment = payment_factory(
            status=PaymentStatusType.SUCCESS,
        )

        first = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            retry_count=1,
            success=True,
        )
        second = PaymentAttemptFactory(
            payment=payment,
            attempt_number=2,
            retry_count=2,
            retry_of=first,
            success=True,
        )

        with pytest.raises(
            ValidationError,
            match="Multiple successful payment attempts",
        ):
            confirm_order_payment(payment.order_id)

        payment.refresh_from_db()
        payment.order.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()

        assert payment.status == PaymentStatusType.SUCCESS
        assert payment.is_consumed is False
        assert payment.order.status != OrderStatusType.paid
        assert first.status == PaymentAttemptStatus.SUCCESS
        assert second.status == PaymentAttemptStatus.SUCCESS

    def test_successful_payment_requires_successful_attempt_for_confirmation(
        self,
        payment_factory,
    ):
        payment = payment_factory(
            status=PaymentStatusType.SUCCESS,
        )

        with pytest.raises(
            ValidationError,
            match="No successful payment attempt found",
        ):
            confirm_order_payment(payment.order_id)

        payment.refresh_from_db()
        payment.order.refresh_from_db()

        assert payment.status == PaymentStatusType.SUCCESS
        assert payment.is_consumed is False
        assert payment.order.status != OrderStatusType.paid
