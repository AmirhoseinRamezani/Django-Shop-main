# tests/e2e/test_checkout.py
import pytest

from order.models import (
    OrderModel,
    OrderStatusType,
)
from order.services.order import OrderService

from tests.assertions import (
    refresh,
    assert_order_created,
    assert_order_item_created,
)

pytestmark = pytest.mark.django_db


class TestCheckoutFlow:

    def test_checkout_success(
        self,
        user,
        address,
        cart_builder,
        product,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product, 2)
            .build()
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        refresh(order)

        assert_order_created(order)

        assert_order_item_created(order)

    def test_checkout_with_coupon(
        self,
        user,
        address,
        coupon,
        cart_builder,
        product,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product)
            .build()
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
            coupon=coupon,
        )

        refresh(order)

        assert order.coupon == coupon
        assert order.coupon_code == coupon.code

    def test_order_saved_in_database(
        self,
        user,
        address,
        cart_builder,
        product,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product)
            .build()
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert OrderModel.objects.filter(
            pk=order.pk,
        ).exists()