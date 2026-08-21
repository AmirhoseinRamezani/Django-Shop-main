
# tests/scenarios/order/test_failed_payment_flow.py
import pytest

from order.services.order import OrderService
from order.services.confirm_payment import confirm_order_payment

from order.models import (
    OrderStatusType,
)

from payment.enums import PaymentStatusType

pytestmark = pytest.mark.django_db

class TestFailedPaymentFlow:

    def test_failed_payment(
        self,
        user,
        address,
        cart,
        product,
        payment_factory,
    ):

        cart.add(product)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        payment_factory(
            order=order,
            status=PaymentStatusType.failed,
        )

        with pytest.raises(Exception):

            confirm_order_payment(order.id)

        order.refresh_from_db()

        assert order.status == OrderStatusType.pending