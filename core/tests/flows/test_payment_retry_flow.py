from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from payment.services.retry import RetryPaymentService
from payment.enums import PaymentStatusType ,PaymentAttemptStatus
from order.models import OrderStatusType

pytestmark = pytest.mark.django_db


class TestRetryPayment:
    
    def test_retry_uses_same_payment_and_creates_new_attempt(
        self,
        payment,
        mocker,
    ):
        first_attempt = PaymentAttemptFactory(
            payment=payment,
            attempt_number=1,
            retry_count=1,
            status=PaymentAttemptStatus.FAILED,
        )

        mocker.patch(
            "payment.services.retry.GatewayService.initiate_payment",
            return_value=self.successful_gateway_result(),
        )

        mocker.patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value="https://gateway.test/AUTH-2",
        )

        url = RetryPaymentService.retry(
            order=payment.order,
            callback_url="https://shop.test/payment/callback",
        )

        payment.refresh_from_db()

        attempts = PaymentAttempt.objects.filter(
            payment=payment,
        ).order_by("attempt_number")

        assert attempts.count() == 2

        retry = attempts.get(
            attempt_number=2,
        )

        assert retry.payment_id == payment.id
        assert retry.retry_of_id == first_attempt.id
        assert retry.retry_count == 2
        assert retry.status == PaymentAttemptStatus.PENDING
        assert retry.authority_id == "AUTH-2"
        assert url == "https://gateway.test/AUTH-2"

    def test_retry_after_failed_payment(
        self,
        failed_order,
        mocker,
    ):
        # Mocks
        mocker.patch(
            "payment.services.retry.GatewayService.payment_request",
            return_value={"Authority": "AUTH123"},
        )
        mocker.patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value="https://gateway.com/pay/AUTH123",
        )

        url = RetryPaymentService.retry(order=failed_order)

        latest_payment = failed_order.payments.last()
        assert latest_payment.status == PaymentStatusType.PENDING

    def test_new_payment_created(
        self,
        failed_order,
        mocker,
    ):
        mocker.patch(
            "payment.services.retry.GatewayService.payment_request",
            return_value={"Authority": "AUTH123"},
        )
        mocker.patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value="https://gateway.com/pay/AUTH123",
        )

        before = failed_order.payments.count()

        RetryPaymentService.retry(order=failed_order)

        assert failed_order.payments.count() == before + 1

    def test_order_back_to_pending(
        self,
        failed_order,
        mocker,
    ):
        mocker.patch(
            "payment.services.retry.GatewayService.payment_request",
            return_value={"Authority": "AUTH123"},
        )
        mocker.patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value="https://gateway.com/pay/AUTH123",
        )

        RetryPaymentService.retry(order=failed_order)

        failed_order.refresh_from_db()
        assert failed_order.status == OrderStatusType.pending

    def test_return_payment_url(
        self,
        failed_order,
        mocker,
    ):
        mocker.patch(
            "payment.services.retry.GatewayService.payment_request",
            return_value={"Authority": "AUTH123"},
        )
        mocker.patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value="https://gateway.com/pay/AUTH123",
        )

        url = RetryPaymentService.retry(order=failed_order)

        assert isinstance(url, str)
        assert "AUTH123" in url


class TestRetry:

    def test_retry_only_after_failed(
        self,
        failed_order,
        mocker,
    ):
        mocker.patch(
            "payment.services.retry.GatewayService.payment_request",
            return_value={"Authority": "AUTH123"},
        )
        mocker.patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value="https://gateway.com/pay/AUTH123",
        )

        RetryPaymentService.retry(order=failed_order)

        latest_payment = failed_order.payments.last()
        assert latest_payment.status == PaymentStatusType.PENDING

    def test_multiple_failed_payments_allowed(
        self,
        failed_order,
        mocker,
    ):
        mocker.patch(
            "payment.services.retry.GatewayService.payment_request",
            return_value={"Authority": "AUTH123"},
        )
        mocker.patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value="https://gateway.com/pay/AUTH123",
        )

        RetryPaymentService.retry(order=failed_order)

        # تغییر وضعیت آخرین پرداخت به FAILED برای شبیه‌سازی شکست مجدد
        last_payment = failed_order.payments.last()
        last_payment.status = PaymentStatusType.FAILED
        last_payment.save()

        url = RetryPaymentService.retry(order=failed_order)

        assert url is not None

    def test_only_one_pending_payment(
        self,
        pending_order,
        pending_payment,
    ):
        with pytest.raises(ValidationError):
            RetryPaymentService.retry(order=pending_order)


class TestAtomicity:

    def test_gateway_failure(
        self,
        failed_order,
        mocker,
    ):
        mocker.patch(
            "payment.services.retry.GatewayService.payment_request",
            side_effect=RuntimeError("Gateway connection error"),
        )

        before = failed_order.payments.count()

        with pytest.raises(RuntimeError):
            RetryPaymentService.retry(order=failed_order)

        assert failed_order.payments.count() == before

    def test_database_rollback(
        self,
        failed_order,
        mocker,
    ):
        mocker.patch(
            "payment.services.retry.GatewayService.payment_request",
            return_value={"Authority": "AUTH123"},
        )
        mocker.patch(
            "payment.services.retry.PaymentFactory.create",
            side_effect=RuntimeError("DB Save Error"),
        )

        with pytest.raises(RuntimeError):
            RetryPaymentService.retry(order=failed_order)


class TestIdempotency:

    def test_second_retry_fails(
        self,
        failed_order,
        mocker,
    ):
        mocker.patch(
            "payment.services.retry.GatewayService.payment_request",
            return_value={"Authority": "AUTH123"},
        )
        mocker.patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value="https://gateway.com/pay/AUTH123",
        )

        # اولین بار موفق می‌شود و یک پرداخت PENDING می‌سازد
        RetryPaymentService.retry(order=failed_order)

        # بار دوم به دلیل داشتن پرداخت PENDING فعال، باید ValidationError دهد
        with pytest.raises(ValidationError):
            RetryPaymentService.retry(order=failed_order)

    def test_no_duplicate_pending(
        self,
        failed_order,
        mocker,
    ):
        mocker.patch(
            "payment.services.retry.GatewayService.payment_request",
            return_value={"Authority": "AUTH123"},
        )
        mocker.patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value="https://gateway.com/pay/AUTH123",
        )

        RetryPaymentService.retry(order=failed_order)

        assert (
            failed_order.payments.filter(
                status=PaymentStatusType.PENDING,
            ).count()
            == 1
        )