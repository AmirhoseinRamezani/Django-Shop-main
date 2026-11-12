# tests/flows/test_refund_flow.py
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from order.models import OrderStatusType
from payment.enums import (
    PaymentGateway,
    PaymentStatusType,
    RefundReason,
    RefundStatus,
)
from payment.exceptions import (
    PaymentAlreadyRefundedError,
    PaymentCurrencyMismatchError,
    PaymentGatewayError,
    PaymentGatewayNotSupportedError,
    PaymentGatewayTimeoutError,
    PaymentInvariantViolation,
    PaymentRefundAmountInvalidError,
)
from payment.models import Refund
from payment.providers.base import (
    GatewayRefundInquiryResult,
    GatewayRefundResult,
)
from payment.repositories.payment_repository import PaymentRepository
from payment.services.refund import RefundService
from tests.factories.payment import RefundFactory


pytestmark = pytest.mark.django_db


# ==========================================================
# HELPERS
# ==========================================================


def _success_result(reference: str = "REFUND-FLOW-1") -> GatewayRefundResult:
    return GatewayRefundResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference=reference,
        gateway_transaction_id=f"TXN-{reference}",
        response_code="100",
        message="Refund successful",
    )


def _failure_result(
    reference: str = "REFUND-FLOW-FAIL",
    message: str = "Gateway rejected",
) -> GatewayRefundResult:
    return GatewayRefundResult(
        success=False,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference=reference,
        gateway_transaction_id=f"TXN-{reference}",
        response_code="-1",
        message=message,
    )


def _inquiry_success(reference: str = "REFUND-INQ-1") -> GatewayRefundInquiryResult:
    return GatewayRefundInquiryResult(
        success=True,
        status=RefundStatus.SUCCESS,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference=reference,
        gateway_transaction_id=f"TXN-{reference}",
        response_code="100",
        message="Refund confirmed",
    )


def _inquiry_failed(reference: str = "REFUND-INQ-FAIL") -> GatewayRefundInquiryResult:
    return GatewayRefundInquiryResult(
        success=False,
        status=RefundStatus.FAILED,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference=reference,
        gateway_transaction_id=f"TXN-{reference}",
        response_code="-1",
        message="Refund rejected by gateway",
    )


def _inquiry_pending() -> GatewayRefundInquiryResult:
    return GatewayRefundInquiryResult(
        success=False,
        status=RefundStatus.PENDING,
        gateway=PaymentGateway.ZARINPAL,
        response_code="UNKNOWN",
        message="Gateway has no definitive result yet",
    )


def _patch_gateway_refund(mocker, result):
    return mocker.patch(
        "payment.services.refund.GatewayService.refund",
        return_value=result,
    )


def _patch_gateway_inquiry(mocker, result):
    return mocker.patch(
        "payment.services.refund.GatewayService.inquire_refund",
        return_value=result,
    )


def _make_pending_refund(payment, *, amount: Decimal, key: str) -> Refund:
    return RefundFactory(
        payment=payment,
        amount=amount,
        currency=payment.currency,
        idempotency_key=key,
        status=RefundStatus.PENDING,
    )


# ==========================================================
# HAPPY PATH
# ==========================================================


class TestRefundHappyPath:

    def test_full_refund_via_refund_order_marks_payment_and_order_refunded(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        _patch_gateway_refund(mocker, _success_result("REFUND-FULL"))

        refund = RefundService.refund_order(
            order_id=paid_order.pk,
            payment_id=consumed_payment.pk,
            actor=admin_user,
            idempotency_key="refund-flow-full-success",
        )

        refund.refresh_from_db()
        consumed_payment.refresh_from_db()
        paid_order.refresh_from_db()

        assert refund.status == RefundStatus.SUCCESS
        assert refund.amount == consumed_payment.amount
        assert consumed_payment.is_refunded is True
        assert consumed_payment.status == PaymentStatusType.SUCCESS
        assert paid_order.status == OrderStatusType.refunded

    def test_partial_refund_via_refund_does_not_mark_payment_refunded(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        partial_amount = consumed_payment.amount // 2
        assert partial_amount > Decimal("0")

        _patch_gateway_refund(mocker, _success_result("REFUND-PARTIAL"))

        refund = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=partial_amount,
            idempotency_key="refund-flow-partial",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        refund.refresh_from_db()
        consumed_payment.refresh_from_db()
        paid_order.refresh_from_db()

        assert refund.status == RefundStatus.SUCCESS
        assert refund.amount == partial_amount
        assert consumed_payment.is_refunded is False
        assert consumed_payment.status == PaymentStatusType.SUCCESS
        assert paid_order.status == OrderStatusType.paid

    def test_refund_persists_request_metadata(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        _patch_gateway_refund(mocker, _success_result("REFUND-META"))

        refund = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=consumed_payment.amount,
            idempotency_key="refund-flow-meta",
            reason=RefundReason.CUSTOMER_REQUEST,
            reason_detail="Customer requested a refund",
            actor=admin_user,
            ip_address="127.0.0.1",
            user_agent="pytest-agent",
            meta={"trace_id": "trace-abc"},
        )

        refund.refresh_from_db()

        assert refund.reason == RefundReason.CUSTOMER_REQUEST
        assert refund.reason_detail == "Customer requested a refund"
        assert refund.ip_address == "127.0.0.1"
        assert refund.user_agent == "pytest-agent"
        assert refund.meta["trace_id"] == "trace-abc"


# ==========================================================
# BOUNDARY / PARTIAL → FULL TRANSITIONS
# ==========================================================


class TestRefundBoundary:

    def test_last_unit_partial_refund_marks_payment_fully_refunded(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        first_amount = consumed_payment.amount - Decimal("1")
        last_unit = Decimal("1")

        _patch_gateway_refund(mocker, _success_result("REFUND-BOUNDARY-1"))
        RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=first_amount,
            idempotency_key="refund-boundary-first",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        _patch_gateway_refund(mocker, _success_result("REFUND-BOUNDARY-2"))
        final = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=last_unit,
            idempotency_key="refund-boundary-second",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        final.refresh_from_db()
        consumed_payment.refresh_from_db()
        paid_order.refresh_from_db()

        assert final.status == RefundStatus.SUCCESS
        assert final.amount == last_unit
        assert consumed_payment.is_refunded is True
        assert paid_order.status == OrderStatusType.refunded

    def test_request_exceeding_remaining_refundable_is_rejected(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        first_amount = consumed_payment.amount - Decimal("1")

        _patch_gateway_refund(mocker, _success_result("REFUND-EXCEED-FIRST"))
        RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=first_amount,
            idempotency_key="refund-exceed-first",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        gateway = _patch_gateway_refund(mocker, _success_result("REFUND-EXCEED"))

        with pytest.raises(
            PaymentRefundAmountInvalidError,
            match="exceeds the remaining refundable balance",
        ):
            RefundService.refund(
                payment_id=consumed_payment.pk,
                amount=Decimal("2"),
                idempotency_key="refund-exceed-second",
                reason=RefundReason.CUSTOMER_REQUEST,
                actor=admin_user,
            )

        gateway.assert_not_called()

    def test_zero_amount_is_rejected_before_persistence(
        self,
        paid_order,
        consumed_payment,
        admin_user,
    ):
        with pytest.raises(
            PaymentRefundAmountInvalidError,
            match="greater than zero",
        ):
            RefundService.refund(
                payment_id=consumed_payment.pk,
                amount=Decimal("0"),
                idempotency_key="refund-zero",
                reason=RefundReason.CUSTOMER_REQUEST,
                actor=admin_user,
            )

        assert Refund.objects.filter(payment=consumed_payment).count() == 0

    def test_negative_amount_is_rejected_before_persistence(
        self,
        paid_order,
        consumed_payment,
        admin_user,
    ):
        with pytest.raises(
            PaymentRefundAmountInvalidError,
            match="greater than zero",
        ):
            RefundService.refund(
                payment_id=consumed_payment.pk,
                amount=Decimal("-1"),
                idempotency_key="refund-negative",
                reason=RefundReason.CUSTOMER_REQUEST,
                actor=admin_user,
            )

        assert Refund.objects.filter(payment=consumed_payment).count() == 0


# ==========================================================
# IDEMPOTENCY
# ==========================================================


class TestRefundIdempotency:

    def test_same_key_and_amount_is_idempotent(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        gateway = _patch_gateway_refund(
            mocker, _success_result("REFUND-IDEMPOTENT"),
        )

        first = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=consumed_payment.amount,
            idempotency_key="refund-flow-idempotent",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )
        second = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=consumed_payment.amount,
            idempotency_key="refund-flow-idempotent",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        assert second.pk == first.pk
        assert (
            Refund.objects.filter(
                payment_id=consumed_payment.pk,
                idempotency_key="refund-flow-idempotent",
            ).count()
            == 1
        )
        gateway.assert_called_once()

    def test_same_key_with_different_amount_is_rejected(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        _patch_gateway_refund(mocker, _success_result("REFUND-KEY-AMOUNT"))

        RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=Decimal("1"),
            idempotency_key="refund-key-amount",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        with pytest.raises(
            PaymentRefundAmountInvalidError,
            match="different refund amount",
        ):
            RefundService.refund(
                payment_id=consumed_payment.pk,
                amount=Decimal("2"),
                idempotency_key="refund-key-amount",
                reason=RefundReason.CUSTOMER_REQUEST,
                actor=admin_user,
            )

    @pytest.mark.parametrize("entry_point", ["refund", "refund_order"])
    def test_partial_refund_key_cannot_be_reused_for_full_refund(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        entry_point,
        mocker,
    ):
        key = f"refund-partial-to-full-{entry_point}"

        total = consumed_payment.amount
        partial_amount = total // 2
        remaining_amount = total - partial_amount
        assert partial_amount > Decimal("0")
        assert remaining_amount > Decimal("0")

        gateway = _patch_gateway_refund(
            mocker, _success_result(f"REF-{entry_point}"),
        )

        partial = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=partial_amount,
            idempotency_key=key,
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        other_pending = RefundFactory(
            payment=consumed_payment,
            amount=remaining_amount,
            currency=consumed_payment.currency,
            idempotency_key=f"{key}-other-reservation",
            status=RefundStatus.PENDING,
        )

        if entry_point == "refund":
            expected_exc = PaymentRefundAmountInvalidError
            expected_match = "different refund amount"
        else:
            expected_exc = PaymentInvariantViolation
            expected_match = "different operation type"

        with pytest.raises(expected_exc, match=expected_match):
            if entry_point == "refund":
                RefundService.refund(
                    payment_id=consumed_payment.pk,
                    amount=total,
                    idempotency_key=key,
                    reason=RefundReason.CUSTOMER_REQUEST,
                    actor=admin_user,
                )
            else:
                RefundService.refund_order(
                    order_id=paid_order.pk,
                    payment_id=consumed_payment.pk,
                    actor=admin_user,
                    idempotency_key=key,
                )

        partial.refresh_from_db()
        other_pending.refresh_from_db()
        consumed_payment.refresh_from_db()
        paid_order.refresh_from_db()

        assert partial.status == RefundStatus.SUCCESS
        assert partial.amount == partial_amount
        assert other_pending.status == RefundStatus.PENDING
        assert Refund.objects.filter(payment=consumed_payment).count() == 2
        assert consumed_payment.is_refunded is False
        assert paid_order.status == OrderStatusType.paid
        gateway.assert_called_once()

    def test_amount_refund_then_full_refund_with_same_key_is_rejected(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        key = "refund-amount-then-full"

        _patch_gateway_refund(mocker, _success_result("REFUND-AMOUNT-THEN-FULL"))

        RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=Decimal("1"),
            idempotency_key=key,
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        with pytest.raises(
            PaymentInvariantViolation,
            match="different operation type",
        ):
            RefundService.refund_order(
                order_id=paid_order.pk,
                payment_id=consumed_payment.pk,
                actor=admin_user,
                idempotency_key=key,
            )


# ==========================================================
# DOUBLE REFUND / PAYMENT STATE
# ==========================================================


class TestRefundPaymentState:

    def test_double_full_refund_is_rejected(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        _patch_gateway_refund(mocker, _success_result("REFUND-DOUBLE"))

        RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=consumed_payment.amount,
            idempotency_key="refund-flow-double-1",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        with pytest.raises(
            PaymentAlreadyRefundedError,
            match="already been refunded",
        ):
            RefundService.refund(
                payment_id=consumed_payment.pk,
                amount=Decimal("1"),
                idempotency_key="refund-flow-double-2",
                reason=RefundReason.CUSTOMER_REQUEST,
                actor=admin_user,
            )


# ==========================================================
# AUTHORIZATION / ORDER ELIGIBILITY
# ==========================================================


class TestRefundAuthorization:

    def test_refund_order_requires_refundable_order_lifecycle(
        self,
        paid_order,
        consumed_payment,
        admin_user,
    ):
        from order.services.state_machine import OrderStateMachine

        # Move the owning Order past the refundable lifecycle states
        # (paid -> processing -> shipped). Both paid and processing are
        # refundable after the order-refund-inventory boundary patch, so
        # shipped is the first lifecycle state that must reject refund
        # finalization.
        OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.processing,
        )
        OrderStateMachine.transition(
            order=paid_order,
            to_status=OrderStatusType.shipped,
        )

        paid_order.refresh_from_db()
        consumed_payment.refresh_from_db()
        assert paid_order.status == OrderStatusType.shipped
        assert consumed_payment.order_id == paid_order.pk

        with pytest.raises(
            PermissionDenied,
            match="not refundable",
        ):
            RefundService.refund_order(
                order_id=paid_order.pk,
                payment_id=consumed_payment.pk,
                actor=admin_user,
                idempotency_key="refund-flow-not-refundable",
            )

    def test_refund_rejects_payment_owned_by_another_order(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        order_factory,
    ):
        from django.utils import timezone

        foreign_order = order_factory()
        foreign_order.status = OrderStatusType.paid
        foreign_order.paid_date = timezone.now()
        foreign_order.save(update_fields=("status", "paid_date"))

        with pytest.raises(
            PaymentInvariantViolation,
            match="does not belong to the requested Order",
        ):
            RefundService.refund_order(
                order_id=foreign_order.pk,
                payment_id=consumed_payment.pk,
                actor=admin_user,
                idempotency_key="refund-flow-wrong-order",
            )

    def test_order_financial_snapshot_cannot_be_rewritten_before_refund(
        self,
        paid_order,
        consumed_payment,
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            type(paid_order).objects.filter(pk=paid_order.pk).update(
                total_price=paid_order.total_price + Decimal("1"),
                payable_price=paid_order.payable_price + Decimal("1"),
                subtotal_price=paid_order.subtotal_price + Decimal("1"),
            )

        paid_order.refresh_from_db()
        consumed_payment.refresh_from_db()
        assert paid_order.payable_price == consumed_payment.amount


# ==========================================================
# GATEWAY OUTCOME PATHS
# ==========================================================


class TestRefundGatewayOutcome:

    def test_confirmed_gateway_failure_marks_refund_failed(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        _patch_gateway_refund(
            mocker,
            _failure_result(message="Gateway rejected the refund"),
        )

        refund = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=consumed_payment.amount,
            idempotency_key="refund-gateway-failure",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        refund.refresh_from_db()
        consumed_payment.refresh_from_db()

        assert refund.status == RefundStatus.FAILED
        assert refund.failure_reason
        assert consumed_payment.is_refunded is False

    def test_gateway_timeout_leaves_refund_pending(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        mocker.patch(
            "payment.services.refund.GatewayService.refund",
            side_effect=PaymentGatewayTimeoutError("gateway timeout"),
        )

        refund = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=consumed_payment.amount,
            idempotency_key="refund-gateway-timeout",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        refund.refresh_from_db()
        consumed_payment.refresh_from_db()

        assert refund.status == RefundStatus.PENDING
        assert refund.response_code == "PaymentGatewayTimeoutError"
        assert consumed_payment.is_refunded is False

    def test_gateway_unsupported_leaves_refund_pending(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        mocker.patch(
            "payment.services.refund.GatewayService.refund",
            side_effect=PaymentGatewayNotSupportedError("not supported"),
        )

        refund = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=consumed_payment.amount,
            idempotency_key="refund-gateway-unsupported",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        refund.refresh_from_db()

        assert refund.status == RefundStatus.PENDING
        assert refund.response_code == "UNSUPPORTED"

    def test_gateway_generic_error_leaves_refund_pending(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        mocker.patch(
            "payment.services.refund.GatewayService.refund",
            side_effect=PaymentGatewayError("transient failure"),
        )

        refund = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=consumed_payment.amount,
            idempotency_key="refund-gateway-generic-error",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        refund.refresh_from_db()

        assert refund.status == RefundStatus.PENDING
        assert refund.response_code == "PaymentGatewayError"


# ==========================================================
# RECONCILIATION
# ==========================================================


class TestRefundReconciliation:

    def test_pending_refund_reconciled_to_success(
        self,
        paid_order,
        consumed_payment,
        mocker,
    ):
        pending = _make_pending_refund(
            consumed_payment,
            amount=consumed_payment.amount,
            key="refund-reconcile-success",
        )

        _patch_gateway_inquiry(mocker, _inquiry_success("REFUND-RECON-OK"))

        result = RefundService.reconcile_pending_refund(refund_id=pending.pk)

        result.refresh_from_db()
        consumed_payment.refresh_from_db()
        paid_order.refresh_from_db()

        assert result.status == RefundStatus.SUCCESS
        assert result.gateway_reference == "REFUND-RECON-OK"
        assert consumed_payment.is_refunded is True
        assert paid_order.status == OrderStatusType.refunded

    def test_pending_refund_reconciled_to_failure(
        self,
        paid_order,
        consumed_payment,
        mocker,
    ):
        pending = _make_pending_refund(
            consumed_payment,
            amount=consumed_payment.amount,
            key="refund-reconcile-failure",
        )

        _patch_gateway_inquiry(mocker, _inquiry_failed())

        result = RefundService.reconcile_pending_refund(refund_id=pending.pk)

        result.refresh_from_db()
        consumed_payment.refresh_from_db()

        assert result.status == RefundStatus.FAILED
        assert result.failure_reason
        assert consumed_payment.is_refunded is False

    def test_pending_refund_remains_pending_on_unknown_inquiry(
        self,
        paid_order,
        consumed_payment,
        mocker,
    ):
        pending = _make_pending_refund(
            consumed_payment,
            amount=consumed_payment.amount,
            key="refund-reconcile-pending",
        )

        _patch_gateway_inquiry(mocker, _inquiry_pending())

        result = RefundService.reconcile_pending_refund(refund_id=pending.pk)

        result.refresh_from_db()
        consumed_payment.refresh_from_db()

        assert result.status == RefundStatus.PENDING
        assert result.response_code == "UNKNOWN"
        assert consumed_payment.is_refunded is False

    def test_terminal_refund_reconciliation_is_noop(
        self,
        paid_order,
        consumed_payment,
        admin_user,
        mocker,
    ):
        _patch_gateway_refund(mocker, _success_result("REFUND-TERMINAL"))

        refund = RefundService.refund(
            payment_id=consumed_payment.pk,
            amount=consumed_payment.amount,
            idempotency_key="refund-terminal-reconcile",
            reason=RefundReason.CUSTOMER_REQUEST,
            actor=admin_user,
        )

        inquiry = mocker.patch(
            "payment.services.refund.GatewayService.inquire_refund",
        )

        result = RefundService.reconcile_pending_refund(refund_id=refund.pk)

        assert result.pk == refund.pk
        assert result.status == RefundStatus.SUCCESS
        inquiry.assert_not_called()


# ==========================================================
# V1 CURRENCY CONTRACT
# ==========================================================


class TestRefundCurrencyContract:

    def test_non_irr_currency_is_rejected_by_v1_contract(self):
        with pytest.raises(
            PaymentCurrencyMismatchError,
            match="IRR",
        ):
            RefundService._validate_v1_currency("USD")