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
from payment.exceptions import PaymentInvariantViolation
from payment.providers.base import GatewayVerificationResult
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