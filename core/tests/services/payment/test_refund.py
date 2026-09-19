from decimal import Decimal
from unittest.mock import patch

import pytest

from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType, RefundStatus
from payment.exceptions import (
    PaymentGatewayError,
    PaymentInvariantViolation,
    PaymentRefundAmountInvalidError,
)
from payment.models import Refund
from payment.providers.base import GatewayRefundResult
from payment.services.refund import RefundService
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory, RefundFactory


pytestmark = pytest.mark.django_db


def refundable_payment(*, amount=Decimal("1000000")):
    payment = PaymentFactory(
        amount=amount,
        status=PaymentStatusType.SUCCESS,
        is_consumed=True,
        is_refunded=False,
    )
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        status=PaymentAttemptStatus.SUCCESS,
    )
    return payment


def refund_result(
    *,
    success=True,
    reference="REFUND-100",
    transaction_id="",
    response_code="100",
    message="Refund successful",
):
    return GatewayRefundResult(
        success=success,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference=reference,
        gateway_transaction_id=transaction_id,
        response_code=response_code,
        message=message,
    )


class TestRefundService:
    def test_partial_refund_is_reserved_and_succeeds(self):
        payment = refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=refund_result(),
        ) as gateway:
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("400000"),
                idempotency_key="refund-partial-1",
                reason="customer_request",
            )

        refund.refresh_from_db()
        payment.refresh_from_db()

        assert refund.status == RefundStatus.SUCCESS
        assert refund.amount == Decimal("400000")
        assert refund.gateway_reference == "REFUND-100"
        assert payment.is_refunded is False
        gateway.assert_called_once()

    def test_full_refund_marks_payment_fully_refunded(self):
        payment = refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=refund_result(reference="REFUND-FULL"),
        ):
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=payment.amount,
                idempotency_key="refund-full-1",
                reason="customer_request",
            )

        refund.refresh_from_db()
        payment.refresh_from_db()

        assert refund.status == RefundStatus.SUCCESS
        assert payment.is_refunded is True

    def test_pending_refund_reservation_blocks_over_refund(self):
        payment = refundable_payment()
        RefundFactory(
            payment=payment,
            amount=Decimal("700000"),
            status=RefundStatus.PENDING,
        )

        with patch(
            "payment.services.refund.GatewayService.refund",
        ) as gateway:
            with pytest.raises(PaymentRefundAmountInvalidError):
                RefundService.refund(
                    payment_id=payment.pk,
                    amount=Decimal("400000"),
                    idempotency_key="refund-over-reserved-1",
                    reason="customer_request",
                )

        gateway.assert_not_called()
        assert Refund.objects.filter(payment=payment).count() == 1

    def test_same_idempotency_key_returns_existing_refund_without_second_gateway_call(self):
        payment = refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=refund_result(reference="REFUND-IDEMPOTENT"),
        ) as gateway:
            first = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-idempotent-1",
                reason="customer_request",
            )
            second = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-idempotent-1",
                reason="customer_request",
            )

        assert first.pk == second.pk
        assert Refund.objects.filter(payment=payment).count() == 1
        gateway.assert_called_once()

    def test_same_idempotency_key_with_different_amount_is_rejected(self):
        payment = refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=refund_result(),
        ):
            RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-key-reuse-1",
                reason="customer_request",
            )

        with pytest.raises(PaymentRefundAmountInvalidError):
            RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("200000"),
                idempotency_key="refund-key-reuse-1",
                reason="customer_request",
            )

    def test_gateway_transport_error_keeps_refund_pending(self):
        payment = refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            side_effect=PaymentGatewayError(
                "gateway unavailable",
                retryable=True,
            ),
        ) as gateway:
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-unknown-1",
                reason="customer_request",
            )

        refund.refresh_from_db()

        assert refund.status == RefundStatus.PENDING
        assert refund.finished_at is None
        gateway.assert_called_once()

    def test_definitive_gateway_rejection_marks_refund_failed(self):
        payment = refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=refund_result(
                success=False,
                reference="",
                response_code="-1",
                message="Rejected",
            ),
        ):
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-rejected-1",
                reason="customer_request",
            )

        refund.refresh_from_db()

        assert refund.status == RefundStatus.FAILED
        assert refund.failure_reason
        assert refund.finished_at is not None

    def test_gateway_success_without_identity_remains_pending(self):
        payment = refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=refund_result(
                reference="",
                transaction_id="",
                message="Accepted but identity missing",
            ),
        ):
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-no-identity-1",
                reason="customer_request",
            )

        refund.refresh_from_db()

        assert refund.status == RefundStatus.PENDING
        assert refund.finished_at is None

    def test_pending_refund_returned_by_idempotent_retry_is_not_executed_again(self):
        payment = refundable_payment()
        pending = RefundFactory(
            payment=payment,
            amount=Decimal("300000"),
            idempotency_key="refund-pending-retry-1",
            status=RefundStatus.PENDING,
        )

        with patch(
            "payment.services.refund.GatewayService.refund",
        ) as gateway:
            result = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-pending-retry-1",
                reason="customer_request",
            )

        assert result.pk == pending.pk
        assert result.status == RefundStatus.PENDING
        gateway.assert_not_called()

    def test_terminal_success_is_not_modified_by_late_finalize(self):
        payment = refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=refund_result(reference="REFUND-LATE"),
        ):
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-terminal-1",
                reason="customer_request",
            )

        original_finished_at = refund.finished_at
        result = RefundService._finalize_success(
            payment_id=payment.pk,
            refund_id=refund.pk,
            gateway_reference="REFUND-LATE",
            gateway_transaction_id="",
            response_code="100",
            gateway_message="Late duplicate response",
            latency_ms=10,
        )

        result.refresh_from_db()

        assert result.status == RefundStatus.SUCCESS
        assert result.finished_at == original_finished_at

    def test_refund_ownership_is_verified_during_finalization(self):
        payment_a = refundable_payment()
        payment_b = refundable_payment()

        refund = RefundFactory(
            payment=payment_a,
            amount=Decimal("100000"),
            status=RefundStatus.PENDING,
        )

        with pytest.raises(PaymentInvariantViolation):
            RefundService._finalize_failure(
                payment_id=payment_b.pk,
                refund_id=refund.pk,
                reason="test",
            )

        refund.refresh_from_db()
        assert refund.status == RefundStatus.PENDING

    def test_gateway_is_called_after_reservation_commit(self):
        payment = refundable_payment()
        observed = {}

        def gateway_call(*, payment, attempt, refund):
            observed["refund_exists"] = Refund.objects.filter(
                pk=refund.pk,
                status=RefundStatus.PENDING,
            ).exists()
            observed["payment_locked"] = False
            return refund_result(reference="REFUND-COMMITTED")

        with patch(
            "payment.services.refund.GatewayService.refund",
            side_effect=gateway_call,
        ):
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("250000"),
                idempotency_key="refund-boundary-1",
                reason="customer_request",
            )

        assert observed["refund_exists"] is True
        assert refund.status == RefundStatus.SUCCESS
