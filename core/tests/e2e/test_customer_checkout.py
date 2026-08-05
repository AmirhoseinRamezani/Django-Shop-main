# tests/e2e/test_customer_checkout.py
import pytest

from order.models import OrderStatusType
from payment.models import PaymentStatusType

from order.services.order import OrderService
from payment.services.services import PaymentService
from payment.services.payment_flow import handle_successful_payment


pytestmark = pytest.mark.django_db


class DummySession(dict):

    modified = False


class TestCustomerCheckout:

    def test_customer_checkout(
        self,
        user,
        address,
        cart_builder,
        product,
        mocker,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product, quantity=2)
            .build()
        )

        gateway = mocker.patch(
            "payment.services.services.ZarinPalSandbox"
        )

        gateway.return_value.payment_request.return_value = {
            "Authority": "AUTH-100",
        }

        gateway.return_value.generate_payment_url.return_value = "payment-url"

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        PaymentService.start_payment(order)

        payment = order.payments.get()

        handle_successful_payment(
            authority=payment.authority_id,
            ref_id=1122,
            response={},
            session=DummySession(),
        )

        order.refresh_from_db()
        payment.refresh_from_db()

        assert order.status == OrderStatusType.paid
        assert payment.status == PaymentStatusType.success
        assert payment.is_consumed
