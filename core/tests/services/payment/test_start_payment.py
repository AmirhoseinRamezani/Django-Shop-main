# tests/services/payment/test_start_payment.py
from unittest.mock import patch
import pytest

from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType
from payment.exceptions import (
    PaymentCreationForbiddenError,
    PaymentGatewayError,
)
from payment.models import PaymentAttempt, PaymentModel
from payment.providers.base import GatewayPaymentResult
from payment.repositories.payment_attempt_repository import PaymentAttemptRepository
from payment.services import PaymentService
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentAttemptFactory

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]

class TestStartPayment:
    CALLBACK_URL = "https://shop.test/payment/verify/"

    def _initiation_result(self, *, authority="AUTH-123"):
        return GatewayPaymentResult(
            success=True,
            gateway=PaymentGateway.ZARINPAL,
            authority=authority,
        )

    @patch("payment.services.gateway_service.GatewayService.current_gateway", return_value=PaymentGateway.ZARINPAL)
    @patch("payment.services.gateway_service.GatewayService.payment_url", return_value="https://gateway.test/pay/AUTH-123")
    @patch("payment.services.gateway_service.GatewayService.initiate_payment")
    def test_creates_payment_and_attempt_before_gateway(
        self, mock_initiate, mock_payment_url, mock_current_gateway
    ):
        mock_initiate.return_value = self._initiation_result()
        order = OrderFactory(payable=True)

        url = PaymentService.start_payment(
            order,
            callback_url=self.CALLBACK_URL,
        )

        payment = PaymentModel.objects.get(order=order)
        attempt = PaymentAttempt.objects.get(payment=payment)

        assert payment.status == PaymentStatusType.PENDING
        assert payment.amount == order.final_price
        assert payment.currency == "IRR"
        assert payment.gateway == PaymentGateway.ZARINPAL
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert attempt.authority_id == "AUTH-123"
        assert url == "https://gateway.test/pay/AUTH-123"
        mock_initiate.assert_called_once()

    @patch("payment.services.gateway_service.GatewayService.current_gateway", return_value=PaymentGateway.ZARINPAL)
    @patch("payment.services.gateway_service.GatewayService.initiate_payment")
    def test_gateway_transport_failure_leaves_pending_execution(
        self, mock_initiate, mock_current_gateway
    ):
        mock_initiate.side_effect = PaymentGatewayError(
            "gateway timeout",
            retryable=True,
        )
        order = OrderFactory(payable=True)

        with pytest.raises(PaymentGatewayError):
            PaymentService.start_payment(
                order,
                callback_url=self.CALLBACK_URL,
            )

        payment = PaymentModel.objects.get(order=order)
        attempt = PaymentAttempt.objects.get(payment=payment)

        assert payment.status == PaymentStatusType.PENDING
        assert attempt.status == PaymentAttemptStatus.PENDING
        assert attempt.authority_id == ""

    @patch("payment.services.gateway_service.GatewayService.current_gateway", return_value=PaymentGateway.ZARINPAL)
    @patch("payment.services.gateway_service.GatewayService.initiate_payment")
    def test_confirmed_gateway_rejection_finalizes_payment_as_failed(
        self, mock_initiate, mock_current_gateway
    ):
        mock_initiate.return_value = GatewayPaymentResult(
            success=False,
            gateway=PaymentGateway.ZARINPAL,
            response_code="-1",
            message="Rejected",
        )
        order = OrderFactory(payable=True)

        with pytest.raises(PaymentGatewayError) as exc:
            PaymentService.start_payment(
                order,
                callback_url=self.CALLBACK_URL,
            )

        assert exc.value.retryable is False

        # بازخوانی صریح از دیتابیس برای دریافت آخرین وضعیت واقعی
        payment = PaymentModel.objects.get(order_id=order.pk)
        attempt = PaymentAttempt.objects.get(payment_id=payment.pk)

        payment.refresh_from_db()
        attempt.refresh_from_db()

        assert payment.status == PaymentStatusType.FAILED
        assert attempt.status == PaymentAttemptStatus.FAILED
        assert attempt.failure_reason == "Rejected"

    @patch("payment.services.gateway_service.GatewayService.current_gateway", return_value=PaymentGateway.ZARINPAL)
    @patch("payment.services.gateway_service.GatewayService.payment_url", return_value="https://gateway.test/pay/AUTH-EXISTING")
    @patch("payment.services.gateway_service.GatewayService.initiate_payment")
    def test_existing_pending_attempt_is_idempotent(
        self, mock_initiate, mock_url, mock_current_gateway, payment_factory
    ):
        order = OrderFactory(payable=True)
        payment = payment_factory(order=order, gateway=PaymentGateway.ZARINPAL)

        attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="AUTH-EXISTING",
        )

        PaymentAttemptRepository.save_gateway_identity(attempt)

        url = PaymentService.start_payment(
            order,
            callback_url=self.CALLBACK_URL,
        )

        assert url == "https://gateway.test/pay/AUTH-EXISTING"
        mock_initiate.assert_not_called()
        mock_url.assert_called_once_with(
            "AUTH-EXISTING",
            gateway=payment.gateway,
        )

    @patch("payment.services.gateway_service.GatewayService.current_gateway", return_value=PaymentGateway.ZARINPAL)
    @patch("payment.services.gateway_service.GatewayService.initiate_payment")
    def test_pending_attempt_without_authority_is_not_reinitiated(
        self, mock_initiate, mock_current_gateway, payment_factory
    ):
        order = OrderFactory(payable=True)
        payment = payment_factory(order=order, gateway=PaymentGateway.ZARINPAL)

        PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            status=PaymentAttemptStatus.PENDING,
            authority_id="",
        )

        with pytest.raises(PaymentGatewayError) as exc:
            PaymentService.start_payment(
                order,
                callback_url=self.CALLBACK_URL,
            )

        assert exc.value.retryable is True
        mock_initiate.assert_not_called()

    def test_expired_order_rejected(self):
        order = OrderFactory(expired=True)

        with pytest.raises(PaymentCreationForbiddenError):
            PaymentService.start_payment(
                order,
                callback_url=self.CALLBACK_URL,
            )

    def test_cancelled_order_rejected(self):
        order = OrderFactory(cancelled=True)

        with pytest.raises(PaymentCreationForbiddenError):
            PaymentService.start_payment(
                order,
                callback_url=self.CALLBACK_URL,
            )