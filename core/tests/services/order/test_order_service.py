# # test/services/order/test_order_service.py
import pytest

from django.core.exceptions import ValidationError

from order.services.order import OrderService
from order.models import OrderStatusType

from tests.builders.order_builder import OrderBuilder


pytestmark = pytest.mark.django_db


class TestCreateOnlineOrder:

    def test_create_order_success(self):

        scenario = (
            OrderBuilder()
            .with_quantity(2)
            .build()
        )

        order = OrderService.create_online_order(
            **scenario
        )

        assert order.pk is not None

        assert order.status == OrderStatusType.pending

        assert order.order_items.count() == 1

        item = order.order_items.first()

        assert item.quantity == 2

        item.product.refresh_from_db()

        assert item.product.stock == 8

    def test_empty_cart(self):

        builder = OrderBuilder()

        with pytest.raises(ValidationError):

            OrderService.create_online_order(

                user=builder.user,

                address=builder.address,

                cart=builder.cart,

            )

    def test_invalid_coupon(self):

        scenario = (
            OrderBuilder()
            .with_coupon(
                expired=True,
            )
            .build()
        )

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                **scenario
            )

    def test_product_not_publish(self):

        scenario = (
            OrderBuilder()
            .with_product(
                draft=True,
            )
            .build()
        )

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                **scenario
            )

    def test_stock_not_enough(self):

        scenario = (
            OrderBuilder()
            .with_product(
                stock=1,
            )
            .with_quantity(5)
            .build()
        )

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                **scenario
            )

    def test_snapshot_saved(self):

        scenario = (
            OrderBuilder()
            .with_coupon()
            .build()
        )

        order = OrderService.create_online_order(
            **scenario
        )

        assert order.full_name

        assert order.phone

        assert order.email

        assert order.address

        assert order.city

        assert order.state

        assert order.coupon_code == scenario["coupon"].code

        assert (
            order.coupon_discount_percent
            ==
            scenario["coupon"].discount_percent
        )

    def test_total_price(self):

        scenario = (
            OrderBuilder()
            .with_quantity(3)
            .build()
        )

        order = OrderService.create_online_order(
            **scenario
        )

        item = order.order_items.first()

        assert order.total_price == (
            item.price * 3
        )

    def test_expire_at_created(self):

        scenario = (
            OrderBuilder()
            .build()
        )

        order = OrderService.create_online_order(
            **scenario
        )

        assert order.expire_at is not None

        assert order.is_expired() is False