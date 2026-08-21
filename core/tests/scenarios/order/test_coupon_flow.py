# tests/scenarios/order/test_coupon_flow.py
import pytest

from order.services.order import OrderService
from order.services.confirm_payment import confirm_order_payment

from order.models import (
    OrderStatusType,
)

from payment.enums import PaymentStatusType

pytestmark = pytest.mark.django_db

class TestCouponCheckout:

    def test_coupon_complete_flow(
        self,
        user,
        address,
        cart,
        product,
        coupon,
        payment_factory,
    ):

        cart.add(product)

        order = OrderService.create_online_order(

            user=user,
            address=address,
            cart=cart,
            coupon=coupon,
        )

        payment_factory(
            order=order,
            status=PaymentStatusType.SUCCESS,
        )

        confirm_order_payment(order.id)

        coupon.refresh_from_db()

        assert coupon.used_count == 1

        order.refresh_from_db()

        assert order.status == OrderStatusType.paid