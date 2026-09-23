from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from payment.enums import PaymentGateway, PaymentStatusType, RefundStatus
from order.models import OrderStatusType
from payment.exceptions import PaymentRefundAmountInvalidError
from payment.providers.base import GatewayRefundResult
from payment.services.refund import RefundService
from tests.concurrency.base import ConcurrentRunner
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_refunds_never_over_refund_one_payment():
    payment = PaymentFactory(
        order__status=OrderStatusType.paid,
        order__paid_date=timezone.now(),
        order__payable_price=Decimal("1000000"),
        amount=Decimal("1000000"),
        status=PaymentStatusType.SUCCESS,
        is_consumed=True,
        is_refunded=False,
    )
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        success=True,
    )

    results = []
    errors = []

    def refund(amount, idempotency_key):
        try:
            result = RefundService.refund(
                payment_id=payment.pk,
                amount=Decimal(amount),
                idempotency_key=idempotency_key,
                reason="customer_request",
            )
            results.append(result.pk)
        except PaymentRefundAmountInvalidError as exc:
            errors.append(exc)

    with patch(
        "payment.services.refund.GatewayService.refund",
        side_effect=lambda **kwargs: GatewayRefundResult(
            success=True,
            gateway=PaymentGateway.ZARINPAL,
            gateway_reference=f"REFUND-{kwargs['refund'].pk}",
            gateway_transaction_id=f"TXN-{kwargs['refund'].pk}",
            response_code="100",
            message="Refund successful",
        ),
    ):
        runner = ConcurrentRunner()
        runner.run(
            lambda: refund("600000", "refund-concurrent-a"),
            lambda: refund("600000", "refund-concurrent-b"),
        )

    assert len(results) == 1
    assert len(errors) == 1

    payment.refresh_from_db()
    refunds = list(
        payment.refunds.order_by("pk").values_list(
            "amount",
            "status",
        )
    )

    assert refunds == [
        (Decimal("600000"), RefundStatus.SUCCESS),
    ]
    assert sum(
        amount for amount, status in refunds if status == RefundStatus.SUCCESS
    ) == Decimal("600000")
