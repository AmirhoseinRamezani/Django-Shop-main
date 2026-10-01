from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied

from order.models import OrderStatusType
from payment.enums import PaymentStatusType, PaymentGateway, RefundReason, RefundStatus
from payment.exceptions import PaymentAlreadyRefundedError
from payment.providers.base import GatewayRefundResult
from payment.services.refund import RefundService
from payment.models import Refund

pytestmark = pytest.mark.django_db


def _success_result(reference="REFUND-FLOW-1"):
    return GatewayRefundResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        gateway_reference=reference,
        gateway_transaction_id=f"TXN-{reference}",
        response_code="100",
        message="Refund successful",
    )


class TestRefundFlow:
    def test_refund_success(self, paid_order, consumed_payment, admin_user):
        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=_success_result(),
        ):
            refund = RefundService.refund_order(
                order_id=paid_order.pk,
                payment_id=consumed_payment.pk,
                actor=admin_user,
                idempotency_key="refund-flow-success",
            )

        refund.refresh_from_db()
        consumed_payment.refresh_from_db()

        assert refund.status == RefundStatus.SUCCESS
        assert consumed_payment.is_refunded is True
        assert consumed_payment.status == PaymentStatusType.SUCCESS
        assert paid_order.status == OrderStatusType.paid

    def test_partial_refund_does_not_mark_payment_fully_refunded(
        self,
        paid_order,
        consumed_payment,
        admin_user,
    ):
        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=_success_result("REFUND-FLOW-PARTIAL"),
        ):
            refund = RefundService.refund(
                payment_id=consumed_payment.pk,
                amount=Decimal("10000"),
                idempotency_key="refund-flow-partial",
                reason=RefundReason.CUSTOMER_REQUEST,
                actor=admin_user,
            )

        refund.refresh_from_db()
        consumed_payment.refresh_from_db()

        assert refund.status == RefundStatus.SUCCESS
        assert consumed_payment.is_refunded is False
        assert consumed_payment.status == PaymentStatusType.SUCCESS

    def test_same_idempotency_key_is_idempotent(
        self,
        paid_order,
        consumed_payment,
        admin_user,
    ):
        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=_success_result("REFUND-FLOW-IDEMPOTENT"),
        ) as gateway:
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
        assert Refund.objects.filter(
            payment_id=consumed_payment.pk,
            idempotency_key="refund-flow-idempotent",
        ).count() == 1
        gateway.assert_called_once()

    def test_double_refund_is_rejected(
        self,
        paid_order,
        consumed_payment,
        admin_user,
    ):
        with patch(
            "payment.services.refund.GatewayService.refund",
            return_value=_success_result("REFUND-FLOW-DOUBLE"),
        ):
            RefundService.refund(
                payment_id=consumed_payment.pk,
                amount=consumed_payment.amount,
                idempotency_key="refund-flow-double-1",
                reason=RefundReason.CUSTOMER_REQUEST,
                actor=admin_user,
            )

            with pytest.raises(PaymentAlreadyRefundedError):
                RefundService.refund(
                    payment_id=consumed_payment.pk,
                    amount=Decimal("1"),
                    idempotency_key="refund-flow-double-2",
                    reason=RefundReason.CUSTOMER_REQUEST,
                    actor=admin_user,
                )

    def test_refund_requires_refundable_order(
        self,
        order,
        consumed_payment,
        admin_user,
    ):
        with pytest.raises(PermissionDenied):
            RefundService.refund_order(
                order_id=order.pk,
                payment_id=consumed_payment.pk,
                actor=admin_user,
                idempotency_key="refund-flow-not-refundable",
            )
