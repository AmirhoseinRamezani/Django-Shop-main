from decimal import Decimal
from threading import Event, Thread

import pytest
from django.core.exceptions import PermissionDenied

from order.models import OrderStatusType
from payment.enums import (
    PaymentAttemptStatus,
    PaymentGateway,
    PaymentStatusType,
)
from payment.models import Refund
from payment.providers.base import GatewayCallback, GatewayVerificationResult
from payment.services.callback import verify_callback
from payment.services.refund import RefundService
from payment.services.verify import verify_payment
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory


pytestmark = pytest.mark.django_db(transaction=True)


def test_refund_cannot_start_while_callback_verification_is_in_flight(admin_user):
    payment = PaymentFactory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-REFUND-CALLBACK-RACE",
    )

    gateway_entered = Event()
    release_gateway = Event()
    callback_errors = []

    result = GatewayVerificationResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-REFUND-CALLBACK-RACE",
        gateway_transaction_id="TX-REFUND-CALLBACK-RACE",
        response_code="100",
        message="verified",
        amount=payment.amount,
        currency=payment.currency,
    )

    def verify_gateway(*args, **kwargs):
        gateway_entered.set()
        assert release_gateway.wait(timeout=10)
        return result

    def callback_worker():
        try:
            verify_callback(
                callback=GatewayCallback(
                    gateway=PaymentGateway.ZARINPAL,
                    authority=attempt.authority_id,
                )
            )
        except BaseException as exc:
            callback_errors.append(exc)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "payment.services.verify.GatewayService.verify",
            verify_gateway,
        )

        thread = Thread(target=callback_worker)
        thread.start()
        assert gateway_entered.wait(timeout=10)

        with pytest.raises(PermissionDenied):
            RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-callback-race-1",
                reason="customer_request",
                actor=admin_user,
            )

        assert Refund.objects.filter(payment=payment).count() == 0

        release_gateway.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert callback_errors == []

    payment.refresh_from_db()
    attempt.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert payment.order.status == OrderStatusType.paid
    assert Refund.objects.filter(payment=payment).count() == 0


def test_refund_cannot_start_while_direct_verification_is_in_flight(admin_user):
    payment = PaymentFactory()
    attempt = PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.PENDING,
        authority_id="AUTH-REFUND-VERIFY-RACE",
    )

    gateway_entered = Event()
    release_gateway = Event()
    verification_errors = []

    result = GatewayVerificationResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference="REF-REFUND-VERIFY-RACE",
        gateway_transaction_id="TX-REFUND-VERIFY-RACE",
        response_code="100",
        message="verified",
        amount=payment.amount,
        currency=payment.currency,
    )

    def verify_gateway(*args, **kwargs):
        gateway_entered.set()
        assert release_gateway.wait(timeout=10)
        return result

    def verification_worker():
        try:
            verify_payment(
                payment_id=payment.pk,
                attempt_id=attempt.pk,
            )
        except BaseException as exc:
            verification_errors.append(exc)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "payment.services.verify.GatewayService.verify",
            verify_gateway,
        )

        thread = Thread(target=verification_worker)
        thread.start()
        assert gateway_entered.wait(timeout=10)

        with pytest.raises(PermissionDenied):
            RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-verify-race-1",
                reason="customer_request",
                actor=admin_user,
            )

        assert Refund.objects.filter(payment=payment).count() == 0

        release_gateway.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert verification_errors == []

    payment.refresh_from_db()
    attempt.refresh_from_db()

    assert payment.status == PaymentStatusType.SUCCESS
    assert payment.is_consumed is True
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert Refund.objects.filter(payment=payment).count() == 0
