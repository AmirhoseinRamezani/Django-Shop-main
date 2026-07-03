# tests/e2e/test_checkout_flow.py
import pytest

from unittest.mock import patch

from order.models import OrderStatusType
from payment.models import PaymentStatusType

from order.services.order import OrderService
from payment.services.services import PaymentService
from payment.services.verify import verify_payment


pytestmark = pytest.mark.django_db


@patch("payment.zarinpal_client.ZarinPalSandbox.payment_request")
@patch("payment.zarinpal_client.ZarinPalSandbox.generate_payment_url")
def test_complete_checkout_flow(
    payment_url,
    payment_request,
    user,
    address,
    cart,
):

    payment_request.return_value = {
        "Authority": "AUTH123"
    }

    payment_url.return_value = "https://gateway.test"

    order = OrderService.create_online_order(
        user=user,
        address=address,
        cart=cart,
    )

    PaymentService.start_payment(order)

    payment = order.payments.get()

    verify_payment(
        authority=payment.authority_id,
        ref_id="999999",
        response={},
    )

    payment.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == PaymentStatusType.success
    assert payment.is_consumed
    assert order.status == OrderStatusType.paid