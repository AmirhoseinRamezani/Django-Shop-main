# tests/scenarios/order/test_checkout_flow.py
import pytest

from order.services.order import OrderService
from order.services.confirm_payment import confirm_order_payment

from order.models import (
    OrderStatusType,
)

from payment.models import (
    PaymentStatusType,
)

pytestmark = pytest.mark.django_db


class TestCheckoutFlow:

    def test_complete_checkout_flow(
        self,
        user,
        address,
        cart,
        product,
        payment_factory,
    ):
        """
        Cart
            ↓
        Create Order
            ↓
        Success Payment
            ↓
        Confirm Payment
            ↓
        Order Paid
        """

        initial_stock = product.stock

        cart.add(
            product,
            quantity=2,
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        payment = payment_factory(
            order=order,
            status=PaymentStatusType.success,
        )

        confirm_order_payment(
            order.id,
        )

        order.refresh_from_db()
        payment.refresh_from_db()
        product.refresh_from_db()

        assert order.status == OrderStatusType.paid

        assert payment.is_consumed

        assert product.stock == initial_stock - 2

        assert order.order_items.count() == 1
        
