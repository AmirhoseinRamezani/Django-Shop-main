from decimal import Decimal

import pytest
from payment.enums import RefundStatus
from payment.exceptions import (
    PaymentCurrencyMismatchError,
    PaymentGatewayIdentityConflictError,
    PaymentInvalidTransitionError,
    PaymentInvariantViolation,
    PaymentRefundAmountInvalidError,
)
from tests.factories.payment import RefundFactory


pytestmark = pytest.mark.django_db


class TestRefundDomain:
    def test_pending_to_success_sets_terminal_fields(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )

        result = refund.mark_success(
            gateway_reference="REF-1",
            response_code="100",
            gateway_message="Refund successful",
            latency_ms=25,
        )

        assert result is refund
        assert refund.status == RefundStatus.SUCCESS
        assert refund.gateway_reference == "REF-1"
        assert refund.failure_reason == ""
        assert refund.finished_at is not None
        assert refund.latency_ms == 25

    def test_pending_to_failed_sets_terminal_fields(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )

        result = refund.mark_failed(
            reason="Provider rejected refund",
            response_code="-1",
            gateway_message="Rejected",
            latency_ms=30,
        )

        assert result is refund
        assert refund.status == RefundStatus.FAILED
        assert refund.failure_reason == "Provider rejected refund"
        assert refund.finished_at is not None
        assert refund.latency_ms == 30

    def test_success_to_success_is_idempotent_for_same_identity(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )
        refund.mark_success(
            gateway_reference="REF-1",
            response_code="100",
        )
        finished_at = refund.finished_at

        result = refund.mark_success(
            gateway_reference="REF-1",
            response_code="101",
        )

        assert result is refund
        assert refund.status == RefundStatus.SUCCESS
        assert refund.finished_at == finished_at
        assert refund.gateway_reference == "REF-1"

    def test_failed_to_failed_is_idempotent(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )
        refund.mark_failed(reason="Provider rejected refund")
        finished_at = refund.finished_at

        result = refund.mark_failed(
            reason="A different late reason",
            response_code="late",
        )

        assert result is refund
        assert refund.status == RefundStatus.FAILED
        assert refund.finished_at == finished_at
        assert refund.failure_reason == "Provider rejected refund"

    def test_success_to_failed_is_rejected(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )
        refund.mark_success(gateway_reference="REF-1")

        with pytest.raises(PaymentInvalidTransitionError):
            refund.mark_failed(reason="Late failure")

    def test_failed_to_success_is_rejected(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )
        refund.mark_failed(reason="Provider rejected refund")

        with pytest.raises(PaymentInvalidTransitionError):
            refund.mark_success(gateway_reference="REF-1")

    def test_success_without_gateway_identity_is_rejected(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )

        with pytest.raises(PaymentInvariantViolation):
            refund.mark_success()

        assert refund.status == RefundStatus.PENDING
        assert refund.finished_at is None

    def test_success_identity_conflict_is_rejected_without_overwrite(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )
        refund.mark_success(
            gateway_reference="REF-A",
            gateway_transaction_id="TX-A",
        )

        with pytest.raises(PaymentGatewayIdentityConflictError):
            refund.mark_success(
                gateway_reference="REF-B",
                gateway_transaction_id="TX-A",
            )

        assert refund.gateway_reference == "REF-A"
        assert refund.gateway_transaction_id == "TX-A"

    def test_success_identity_can_be_enriched_without_overwrite(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )
        refund.mark_success(
            gateway_transaction_id="TX-A",
        )

        refund.mark_success(
            gateway_reference="REF-A",
            gateway_transaction_id="TX-A",
        )

        assert refund.gateway_reference == "REF-A"
        assert refund.gateway_transaction_id == "TX-A"

    def test_terminal_refund_rejects_gateway_evidence_updates(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )
        refund.mark_success(gateway_reference="REF-1")

        with pytest.raises(PaymentInvalidTransitionError):
            refund.register_gateway_response(
                response_code="late",
                gateway_message="Late evidence",
            )

    def test_validate_against_payment_rejects_amount_overflow(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("1100000"),
        )

        with pytest.raises(PaymentRefundAmountInvalidError):
            refund.validate_against_payment(
                payment_amount=Decimal("1000000"),
                payment_currency=refund.currency,
            )

    def test_validate_against_payment_rejects_currency_mismatch(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )

        with pytest.raises(PaymentCurrencyMismatchError):
            refund.validate_against_payment(
                payment_amount=Decimal("1000000"),
                payment_currency="USD",
            )

    def test_successful_refund_domain_state_passes_clean(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )
        refund.mark_success(
            gateway_reference="REF-1",
        )

        refund.full_clean()

    def test_pending_refund_has_no_finished_timestamp(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )

        assert refund.finished_at is None

    def test_refund_model_exposes_full_payment_refund_semantics(self):
        refund = RefundFactory(
            status=RefundStatus.PENDING,
            amount=Decimal("300000"),
        )

        assert refund.is_full_payment_refund(
            payment_amount=Decimal("300000"),
        )
        assert not refund.is_full_payment_refund(
            payment_amount=Decimal("1000000"),
        )
