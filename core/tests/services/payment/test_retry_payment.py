from unittest.mock import patch

import pytest

from payment.enums import PaymentGateway
from payment.providers.base import GatewayPaymentResult
from payment.services.retry import RetryPaymentService
from tests.factories.order import OrderFactory
from tests.factories.payment import PaymentAttemptFactory, PaymentFactory


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.service,
]


def test_retry_uses_immutable_payment_amount_as_gateway_amount():
    order = OrderFactory()
    payment = PaymentFactory(order=order)
    original_amount = payment.amount
    PaymentAttemptFactory(
        payment=payment,
        attempt_number=1,
        failed=True,
    )

    result = GatewayPaymentResult(
        success=True,
        gateway=PaymentGateway.ZARINPAL,
        authority="AUTH-RETRY-SNAPSHOT",
    )

    with (
        patch(
            "payment.services.retry.GatewayService.initiate_payment",
            return_value=result,
        ) as initiate,
        patch(
            "payment.services.retry.GatewayService.payment_url",
            return_value="https://gateway.test/pay/AUTH-RETRY-SNAPSHOT",
        ),
    ):
        url = RetryPaymentService.retry(
            order=order,
            callback_url="https://shop.test/payment/verify/",
        )

    assert url == "https://gateway.test/pay/AUTH-RETRY-SNAPSHOT"
    assert initiate.call_args.kwargs["amount"] == original_amount
    assert initiate.call_args.kwargs["currency"] == "IRR"

    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payable_price == original_amount
    assert payment.amount == original_amount