from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone
from django.core.exceptions import PermissionDenied

from payment.enums import PaymentAttemptStatus, PaymentGateway, PaymentStatusType, RefundStatus
from order.models import OrderStatusType
from payment.exceptions import (
    PaymentGatewayError,
    PaymentGatewayNotSupportedError,
    PaymentInvariantViolation,
    PaymentRefundAmountInvalidError,
    PaymentGatewayIdentityConflictError,
)
from payment.models import Refund
from payment.providers.base import (
    GatewayRefundInquiryResult,
    GatewayRefundResult,
)
from payment.repositories.refund_repository import RefundRepository
from payment.services.refund import RefundService
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory, RefundFactory


pytestmark = pytest.mark.django_db


def refundable_payment(*, amount=Decimal("1000000")):
    payment = PaymentFactory(
        order__status=OrderStatusType.paid,
        order__paid_date=timezone.now(),
        order__payable_price=amount,
        amount=amount,
        status=PaymentStatusType.SUCCESS,
        is_consumed=True,
        is_refunded=False,
    )
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        success=True,
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
    def test_partial_refund_is_reserved_and_succeeds(self, admin_user):
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
                actor=admin_user,
            )

        refund.refresh_from_db()
        payment.refresh_from_db()

        assert refund.status == RefundStatus.SUCCESS
        assert refund.amount == Decimal("400000")
        assert refund.gateway_reference == "REFUND-100"
        assert payment.is_refunded is False
        gateway.assert_called_once()

    def test_full_refund_marks_payment_fully_refunded(self, admin_user):
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
                actor=admin_user,
            )

        refund.refresh_from_db()
        payment.refresh_from_db()

        assert refund.status == RefundStatus.SUCCESS
        assert payment.is_refunded is True

    def test_pending_refund_reservation_blocks_over_refund(self, admin_user):
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
                actor=admin_user,
                )

        gateway.assert_not_called()
        assert Refund.objects.filter(payment=payment).count() == 1

    def test_same_idempotency_key_returns_existing_refund_without_second_gateway_call(self, admin_user):
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
                actor=admin_user,
            )
            second = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-idempotent-1",
                reason="customer_request",
                actor=admin_user,
            )

        assert first.pk == second.pk
        assert Refund.objects.filter(payment=payment).count() == 1
        gateway.assert_called_once()

    def test_same_idempotency_key_with_different_amount_is_rejected(self, admin_user):
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
                actor=admin_user,
            )

        with pytest.raises(PaymentRefundAmountInvalidError):
            RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("200000"),
                idempotency_key="refund-key-reuse-1",
                reason="customer_request",
                actor=admin_user,
            )

    def test_gateway_transport_error_keeps_refund_pending(self, admin_user):
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
                actor=admin_user,
            )

        refund.refresh_from_db()

        assert refund.status == RefundStatus.PENDING
        assert refund.finished_at is None
        gateway.assert_called_once()

    def test_definitive_gateway_rejection_marks_refund_failed(self, admin_user):
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
                actor=admin_user,
            )

        refund.refresh_from_db()

        assert refund.status == RefundStatus.FAILED
        assert refund.failure_reason
        assert refund.finished_at is not None

    def test_gateway_success_without_identity_remains_pending(self, admin_user):
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
                actor=admin_user,
            )

        refund.refresh_from_db()

        assert refund.status == RefundStatus.PENDING
        assert refund.finished_at is None

    def test_pending_refund_returned_by_idempotent_retry_is_not_executed_again(self, admin_user):
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
                actor=admin_user,
            )

        assert result.pk == pending.pk
        assert result.status == RefundStatus.PENDING
        gateway.assert_not_called()

    def test_stale_pending_refund_is_not_reexecuted_by_normal_retry(self, admin_user):
        payment = refundable_payment()
        pending = RefundFactory(
            payment=payment,
            amount=Decimal("300000"),
            idempotency_key="refund-stale-retry-1",
            status=RefundStatus.PENDING,
        )

        cutoff = timezone.now() - timedelta(minutes=10)
        Refund.objects.filter(pk=pending.pk).update(
            requested_at=cutoff - timedelta(seconds=1),
        )

        candidates = list(
            RefundRepository.stale_pending(
                requested_before=cutoff,
            )
        )

        assert candidates == [pending]

        with patch(
            "payment.services.refund.GatewayService.refund",
        ) as gateway:
            result = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-stale-retry-1",
                reason="customer_request",
                actor=admin_user,
            )

        result.refresh_from_db()

        assert result.pk == pending.pk
        assert result.status == RefundStatus.PENDING
        gateway.assert_not_called()

    def test_terminal_success_is_not_modified_by_late_finalize(self, admin_user):
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
                actor=admin_user,
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

    def test_refund_ownership_is_verified_during_finalization(self, admin_user):
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

    def test_gateway_is_called_after_reservation_commit(self, admin_user):
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
                actor=admin_user,
            )

        assert observed["refund_exists"] is True
        assert refund.status == RefundStatus.SUCCESS

    def test_pending_refund_recovery_uses_inquiry_and_can_finalize_success(self, admin_user):
        payment = refundable_payment()
        pending = RefundFactory(
            payment=payment,
            amount=Decimal("300000"),
            idempotency_key="refund-recovery-success-1",
            status=RefundStatus.PENDING,
        )

        inquiry = GatewayRefundInquiryResult(
            success=True,
            status=RefundStatus.SUCCESS,
            gateway=PaymentGateway.ZARINPAL,
            gateway_reference="RECOVERED-REF-1",
            response_code="100",
            message="Refund completed",
            amount=pending.amount,
            currency=payment.currency,
        )

        with patch(
            "payment.services.refund.GatewayService.inquire_refund",
            return_value=inquiry,
        ) as gateway:
            with patch(
                "payment.services.refund.GatewayService.refund",
            ) as refund_gateway:
                result = RefundService.reconcile_pending_refund(
                    refund_id=pending.pk,
                )

        result.refresh_from_db()
        payment.refresh_from_db()

        assert result.status == RefundStatus.SUCCESS
        assert result.gateway_reference == "RECOVERED-REF-1"
        assert payment.is_refunded is False
        gateway.assert_called_once()
        refund_gateway.assert_not_called()

    def test_pending_refund_recovery_keeps_pending_when_provider_reports_pending(self, admin_user):
        payment = refundable_payment()
        pending = RefundFactory(
            payment=payment,
            amount=Decimal("300000"),
            idempotency_key="refund-recovery-pending-1",
            status=RefundStatus.PENDING,
        )

        inquiry = GatewayRefundInquiryResult(
            success=False,
            status=RefundStatus.PENDING,
            gateway=PaymentGateway.ZARINPAL,
            response_code="PENDING",
            message="Provider has no terminal result",
            amount=pending.amount,
            currency=payment.currency,
        )

        with patch(
            "payment.services.refund.GatewayService.inquire_refund",
            return_value=inquiry,
        ) as gateway:
            result = RefundService.reconcile_pending_refund(
                refund_id=pending.pk,
            )

        result.refresh_from_db()

        assert result.status == RefundStatus.PENDING
        assert result.finished_at is None
        assert result.response_code == "PENDING"
        gateway.assert_called_once()

    def test_pending_refund_recovery_marks_definitive_failure(self, admin_user):
        payment = refundable_payment()
        pending = RefundFactory(
            payment=payment,
            amount=Decimal("300000"),
            idempotency_key="refund-recovery-failed-1",
            status=RefundStatus.PENDING,
        )

        inquiry = GatewayRefundInquiryResult(
            success=False,
            status=RefundStatus.FAILED,
            gateway=PaymentGateway.ZARINPAL,
            response_code="-1",
            message="Provider rejected refund",
            amount=pending.amount,
            currency=payment.currency,
        )

        with patch(
            "payment.services.refund.GatewayService.inquire_refund",
            return_value=inquiry,
        ):
            result = RefundService.reconcile_pending_refund(
                refund_id=pending.pk,
            )

        result.refresh_from_db()

        assert result.status == RefundStatus.FAILED
        assert result.failure_reason == "Provider rejected refund"
        assert result.finished_at is not None

    def test_pending_refund_recovery_does_not_retry_refund_execution(self, admin_user):
        payment = refundable_payment()
        pending = RefundFactory(
            payment=payment,
            amount=Decimal("300000"),
            idempotency_key="refund-recovery-no-retry-1",
            status=RefundStatus.PENDING,
        )

        inquiry = GatewayRefundInquiryResult(
            success=True,
            status=RefundStatus.SUCCESS,
            gateway=PaymentGateway.ZARINPAL,
            gateway_transaction_id="RECOVERED-TX-1",
            amount=pending.amount,
            currency=payment.currency,
        )

        with patch(
            "payment.services.refund.GatewayService.inquire_refund",
            return_value=inquiry,
        ) as inquiry_gateway:
            with patch(
                "payment.services.refund.GatewayService.refund",
            ) as refund_gateway:
                RefundService.reconcile_pending_refund(
                    refund_id=pending.pk,
                )

        inquiry_gateway.assert_called_once()
        refund_gateway.assert_not_called()



    def test_pending_refund_recovery_stays_pending_without_provider_inquiry_support(self, admin_user):
        payment = refundable_payment()
        pending = RefundFactory(
            payment=payment,
            amount=Decimal("300000"),
            idempotency_key="refund-recovery-unsupported-inquiry-1",
            status=RefundStatus.PENDING,
        )

        with patch(
            "payment.services.refund.GatewayService.inquire_refund",
            side_effect=PaymentGatewayNotSupportedError(
                "Refund inquiry is not supported.",
            ),
        ) as inquiry_gateway:
            with pytest.raises(PaymentGatewayNotSupportedError):
                RefundService.reconcile_pending_refund(
                    refund_id=pending.pk,
                )

        result = Refund.objects.get(pk=pending.pk)

        assert result.status == RefundStatus.PENDING
        assert result.finished_at is None
        inquiry_gateway.assert_called_once()


    def test_refund_rejects_explicit_missing_actor(self, payment):
        with pytest.raises(PermissionDenied):
            RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("100000"),
                idempotency_key="refund-no-actor-1",
                reason="customer_request",
                actor=None,
            )

    def test_refund_rejects_non_staff_actor(self, payment):
        actor = UserFactory()
        with pytest.raises(PermissionDenied):
            RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("100000"),
                idempotency_key="refund-non-staff-1",
                reason="customer_request",
                actor=actor,
            )

    def test_duplicate_success_with_same_gateway_identity_is_idempotent(self, admin_user):
        payment = refundable_payment()
        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=refund_result(reference="REFUND-SAME"),
        ):
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-same-identity-1",
                reason="customer_request",
                actor=admin_user,
            )

        result = RefundService._finalize_success(
            payment_id=payment.pk,
            refund_id=refund.pk,
            gateway_reference="REFUND-SAME",
            gateway_transaction_id="",
            response_code="100",
            gateway_message="Duplicate success",
            latency_ms=1,
        )

        result.refresh_from_db()
        assert result.gateway_reference == "REFUND-SAME"
        assert result.status == RefundStatus.SUCCESS

    def test_duplicate_success_with_conflicting_gateway_identity_is_rejected(self, admin_user):
        payment = refundable_payment()
        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=refund_result(reference="REFUND-A"),
        ):
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-conflict-identity-1",
                reason="customer_request",
                actor=admin_user,
            )

        with pytest.raises(PaymentGatewayIdentityConflictError):
            RefundService._finalize_success(
                payment_id=payment.pk,
                refund_id=refund.pk,
                gateway_reference="REFUND-B",
                gateway_transaction_id="",
                response_code="100",
                gateway_message="Conflicting duplicate success",
                latency_ms=1,
            )

        refund.refresh_from_db()
        assert refund.gateway_reference == "REFUND-A"
        assert refund.status == RefundStatus.SUCCESS

    def test_success_finalization_enriches_missing_gateway_identity(self, admin_user):
        payment = refundable_payment()
        pending = RefundFactory(
            payment=payment,
            amount=Decimal("300000"),
            idempotency_key="refund-enrich-identity-1",
            status=RefundStatus.PENDING,
        )

        first = RefundService._finalize_success(
            payment_id=payment.pk,
            refund_id=pending.pk,
            gateway_reference="",
            gateway_transaction_id="TX-A",
            response_code="100",
            gateway_message="Success",
            latency_ms=1,
        )
        assert first.status == RefundStatus.SUCCESS

        result = RefundService._finalize_success(
            payment_id=payment.pk,
            refund_id=pending.pk,
            gateway_reference="REF-A",
            gateway_transaction_id="TX-A",
            response_code="100",
            gateway_message="Duplicate success with enrichment",
            latency_ms=1,
        )

        result.refresh_from_db()
        assert result.gateway_reference == "REF-A"
        assert result.gateway_transaction_id == "TX-A"


    def test_unsupported_refund_capability_stays_pending_with_explicit_evidence(
        self,
        admin_user,
    ):
        payment = refundable_payment()

        with patch(
            "payment.services.refund.GatewayService.refund",
            side_effect=PaymentGatewayNotSupportedError(
                "Refund is not supported.",
            ),
        ) as gateway:
            refund = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal("300000"),
                idempotency_key="refund-unsupported-1",
                reason="customer_request",
                actor=admin_user,
            )

        refund.refresh_from_db()
        assert refund.status == RefundStatus.PENDING
        assert refund.finished_at is None
        assert refund.response_code == "UNSUPPORTED"
        assert refund.gateway_message == "Gateway refund operation is not supported."
        gateway.assert_called_once()
