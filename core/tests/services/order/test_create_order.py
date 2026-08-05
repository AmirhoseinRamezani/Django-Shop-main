# # test/services/order/test_create_order.py
# import pytest

# from django.core.exceptions import ValidationError

# from order.services.order import OrderService
# from order.models import OrderStatusType
# from shop.constants import ProductStatusType

# from tests.assertions import (
#     assert_order_created,
#     assert_stock_decreased,
#     assert_order_item_created,
#     refresh,
# )
# from tests.factories.order import OrderFactory

# pytestmark = pytest.mark.django_db


# class TestCreateOnlineOrder:

#     def test_create_order(
#         self,
#         user,
#         address,
#         cart_builder,
#         product,
#     ):
#         cart = (
#             cart_builder
#             .for_user(user)
#             .with_item(product, quantity=2)
#             .build()
#         )

#         old_stock = product.stock

#         order = OrderService.create_online_order(
#             user=user,
#             address=address,
#             cart=cart,
#         )

#         refresh(order, product)

#         assert_order_created(order)

#         assert order.status == OrderStatusType.pending

#         assert_order_item_created(
#             order,
#             count=1,
#         )

#         assert_stock_decreased(
#             product,
#             old_stock,
#             2,
#         )

#     def test_create_order_with_coupon(
#         self,
#         user,
#         address,
#         coupon,
#         cart_builder,
#         product,
#     ):
#         cart = (
#             cart_builder
#             .for_user(user)
#             .with_item(product)
#             .build()
#         )

#         order = OrderService.create_online_order(
#             user=user,
#             address=address,
#             cart=cart,
#             coupon=coupon,
#         )

#         assert order.coupon == coupon

#         assert order.coupon_code == coupon.code

#     def test_empty_cart(
#         self,
#         user,
#         address,
#         cart,
#     ):
#         with pytest.raises(ValidationError):

#             OrderService.create_online_order(
#                 user=user,
#                 address=address,
#                 cart=cart,
#             )

#     def test_invalid_coupon(
#         self,
#         user,
#         address,
#         expired_coupon,
#         cart_builder,
#         product,
#     ):
#         cart = (
#             cart_builder
#             .for_user(user)
#             .with_item(product)
#             .build()
#         )

#         with pytest.raises(ValidationError):

#             OrderService.create_online_order(
#                 user=user,
#                 address=address,
#                 cart=cart,
#                 coupon=expired_coupon,
#             )

#     def test_product_not_published(
#         self,
#         user,
#         address,
#         draft_product,
#         cart_builder,
#     ):
#         cart = (
#             cart_builder
#             .for_user(user)
#             .with_item(draft_product)
#             .build()
#         )

#         with pytest.raises(ValidationError):

#             OrderService.create_online_order(
#                 user=user,
#                 address=address,
#                 cart=cart,
#             )

#     def test_stock_not_enough(
#         self,
#         user,
#         address,
#         out_of_stock_product,
#         cart_builder,
#     ):
#         cart = (
#             cart_builder
#             .for_user(user)
#             .with_item(
#                 out_of_stock_product,
#                 quantity=10,
#             )
#             .build()
#         )

#         with pytest.raises(ValidationError):

#             OrderService.create_online_order(
#                 user=user,
#                 address=address,
#                 cart=cart,
#             )

#     def test_create_multiple_items(
#         self,
#         user,
#         address,
#         product_factory,
#         cart_builder,
#     ):
#         p1 = product_factory()

#         p2 = product_factory()

#         cart = (
#             cart_builder
#             .for_user(user)
#             .with_item(p1, 2)
#             .with_item(p2, 3)
#             .build()
#         )

#         order = OrderService.create_online_order(
#             user=user,
#             address=address,
#             cart=cart,
#         )

#         assert order.order_items.count() == 2

#     def test_snapshot_saved(
#         self,
#         user,
#         address,
#         cart_builder,
#         product,
#     ):
#         cart = (
#             cart_builder
#             .for_user(user)
#             .with_item(product)
#             .build()
#         )

#         order = OrderService.create_online_order(
#             user=user,
#             address=address,
#             cart=cart,
#         )

#         assert order.full_name == order.full_name

#         assert order.phone == order.phone

#         assert order.address == address.address

#         assert order.city == address.city

#         assert order.state == address.state

#         assert order.zip_code == address.zip_code

import pytest

from decimal import Decimal

from django.core.exceptions import ValidationError

from tests.base import BaseTestCase

from order.services.order import OrderService

from shop.constants import ProductStatusType


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]


class TestCreateOnlineOrder(BaseTestCase):

    def test_create_simple_order(
        self,
        user,
        cart_factory,
        cart_item_factory,
        product_factory,
        address,
    ):
        product = product_factory(
            price=100000,
            stock=5,
        )

        cart = cart_factory(user=user)

        cart_item_factory(
            cart=cart,
            product=product,
            quantity=2,
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        self.assert_order_created(order)

        assert order.total_price == Decimal("200000")

        assert order.order_items.count() == 1

        product.refresh_from_db()

        assert product.stock == 3

    def test_multiple_products(
        self,
        user,
        cart_factory,
        cart_item_factory,
        product_factory,
        address,
    ):
        p1 = product_factory(price=100000)

        p2 = product_factory(price=50000)

        cart = cart_factory(user=user)

        cart_item_factory(
            cart=cart,
            product=p1,
            quantity=2,
        )

        cart_item_factory(
            cart=cart,
            product=p2,
            quantity=3,
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        self.assert_order_created(order)

        assert order.total_price == Decimal("350000")

    def test_discounted_product(
        self,
        user,
        cart_factory,
        cart_item_factory,
        product_factory,
        address,
    ):
        product = product_factory(
            price=100000,
            discount_percent=20,
        )

        cart = cart_factory(user=user)

        cart_item_factory(
            cart=cart,
            product=product,
            quantity=2,
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert order.total_price == Decimal("160000")

    def test_create_order_with_coupon(
        self,
        user,
        coupon,
        cart_factory,
        cart_item_factory,
        product_factory,
        address,
    ):
        product = product_factory()

        cart = cart_factory(user=user)

        cart_item_factory(
            cart=cart,
            product=product,
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
            coupon=coupon,
        )

        assert order.coupon == coupon

        assert order.coupon_code == coupon.code

        assert (
            order.coupon_discount_percent
            == coupon.discount_percent
        )

    def test_empty_cart(
        self,
        user,
        cart_factory,
        address,
    ):
        cart = cart_factory(user=user)

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

    def test_draft_product(
        self,
        user,
        cart_factory,
        cart_item_factory,
        product_factory,
        address,
    ):
        product = product_factory(
            status=ProductStatusType.DRAFT,
        )

        cart = cart_factory(user=user)

        cart_item_factory(
            cart=cart,
            product=product,
        )

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

    def test_out_of_stock(
        self,
        user,
        cart_factory,
        cart_item_factory,
        product_factory,
        address,
    ):
        product = product_factory(
            stock=1,
        )

        cart = cart_factory(user=user)

        cart_item_factory(
            cart=cart,
            product=product,
            quantity=2,
        )

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

    def test_invalid_coupon(
        self,
        user,
        coupon_factory,
        cart_factory,
        cart_item_factory,
        product_factory,
        address,
    ):
        coupon = coupon_factory(expired=True)

        product = product_factory()

        cart = cart_factory(user=user)

        cart_item_factory(
            cart=cart,
            product=product,
        )

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
                coupon=coupon,
            )

    def test_order_expire_time(
        self,
        user,
        cart_factory,
        cart_item_factory,
        product_factory,
        address,
    ):
        product = product_factory()

        cart = cart_factory(user=user)

        cart_item_factory(
            cart=cart,
            product=product,
        )

        before = self.freeze_time()

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert order.expire_at > before()

    def test_snapshot(
        self,
        user,
        cart_factory,
        cart_item_factory,
        product_factory,
        address,
    ):
        product = product_factory()

        cart = cart_factory(user=user)

        cart_item_factory(
            cart=cart,
            product=product,
        )

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert order.full_name == user.profile.get_fullname()

        assert order.phone == user.profile.phone_number

        assert order.email == user.email

        assert order.city == address.city