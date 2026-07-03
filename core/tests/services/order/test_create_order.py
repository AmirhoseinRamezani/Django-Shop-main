# test/services/order/test_create_order.py
import pytest

from django.core.exceptions import ValidationError

from order.services.order import OrderService
from order.models import OrderStatusType
from shop.constants import ProductStatusType

from tests.assertions import (
    assert_order_created,
    assert_stock_decreased,
    assert_order_item_created,
    refresh,
)

pytestmark = pytest.mark.django_db


class TestCreateOnlineOrder:

    def test_create_order(
        self,
        user,
        address,
        cart_builder,
        product,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product, quantity=2)
            .build()
        )

        old_stock = product.stock

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        refresh(order, product)

        assert_order_created(order)

        assert order.status == OrderStatusType.pending

        assert_order_item_created(
            order,
            count=1,
        )

        assert_stock_decreased(
            product,
            old_stock,
            2,
        )

    def test_create_order_with_coupon(
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

        assert order.coupon == coupon

        assert order.coupon_code == coupon.code

    def test_empty_cart(
        self,
        user,
        address,
        cart,
    ):
        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

    def test_invalid_coupon(
        self,
        user,
        address,
        expired_coupon,
        cart_builder,
        product,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(product)
            .build()
        )

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
                coupon=expired_coupon,
            )

    def test_product_not_published(
        self,
        user,
        address,
        draft_product,
        cart_builder,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(draft_product)
            .build()
        )

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

    def test_stock_not_enough(
        self,
        user,
        address,
        out_of_stock_product,
        cart_builder,
    ):
        cart = (
            cart_builder
            .for_user(user)
            .with_item(
                out_of_stock_product,
                quantity=10,
            )
            .build()
        )

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

    def test_create_multiple_items(
        self,
        user,
        address,
        product_factory,
        cart_builder,
    ):
        p1 = product_factory()

        p2 = product_factory()

        cart = (
            cart_builder
            .for_user(user)
            .with_item(p1, 2)
            .with_item(p2, 3)
            .build()
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert order.order_items.count() == 2

    def test_snapshot_saved(
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

        assert order.full_name

        assert order.phone

        assert order.address == address.address

        assert order.city == address.city

        assert order.state == address.state

        assert order.zip_code == address.zip_code