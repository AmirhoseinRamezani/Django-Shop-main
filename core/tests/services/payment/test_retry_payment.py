from decimal import Decimal
from unittest.mock import patch

import pytest

from payment.exceptions import PaymentInvariantViolation
from payment.models import PaymentAttempt
from payment.services.retry import RetryPaymentService
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.service,
]


def test_retry_rejects_changed_order_financial_snapshot_before_gateway_io():
    order = OrderFactory()
    payment = PaymentFactory(order=order)
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        failed=True,
    )

    order.payable_price = Decimal("101000")
    order.save(update_fields=("payable_price",))

    with patch(
        "payment.services.retry.GatewayService.initiate_payment"
    ) as initiate:
        with pytest.raises(
            PaymentInvariantViolation,
            match="Payment amount does not match the Order financial snapshot",
        ):
            RetryPaymentService.retry(
                order=order,
                callback_url="https://shop.test/payment/verify/",
            )

    initiate.assert_not_called()
    assert PaymentAttempt.objects.filter(payment=payment).count() == 1