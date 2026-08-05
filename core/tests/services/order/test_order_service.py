# # tests/services/order/test_order_service.py
# import pytest

# from django.core.exceptions import ValidationError

# from order.services.order import OrderService
# from order.models import OrderStatusType

# from tests.builders.order_builder import OrderBuilder
# from tests.builders.checkout_builder import CheckoutBuilder

# pytestmark = pytest.mark.django_db

# class TestCreateOnlineOrder:

#     def test_create_order_success(self):

#         scenario = (
#             CheckoutBuilder()
#             .with_quantity(2)
#             .build()
#         )

#         order = OrderService.create_online_order(
#             **scenario
#         )

#         assert order.pk is not None

#         assert order.status == OrderStatusType.pending

#         assert order.order_items.count() == 1

#         item = order.order_items.first()

#         assert item.quantity == 2

#         item.product.refresh_from_db()

#         assert item.product.stock == 8

#     def test_empty_cart(self):

#         builder = OrderBuilder()

#         with pytest.raises(ValidationError):

#             OrderService.create_online_order(

#                 user=builder.user,

#                 address=builder.address,

#                 cart=builder.cart,

#             )

#     def test_invalid_coupon(self):

#         scenario = (
#             CheckoutBuilder()
#             .with_coupon(expired=True)
#             .build()
#         )

#         with pytest.raises(ValidationError):

#             OrderService.create_online_order(
#                 **scenario
#             )

#     def test_product_not_publish(self):

#         scenario = (
#             CheckoutBuilder()
#             .with_product(draft=True)
#             .build()
#         )

#         with pytest.raises(ValidationError):

#             OrderService.create_online_order(
#                 **scenario
#             )

#     def test_stock_not_enough(self):

#         scenario = (
#             CheckoutBuilder()
#             .with_product(stock=1)
#             .with_quantity(5)
#             .scenario()
#         )

#         with pytest.raises(ValidationError):

#             OrderService.create_online_order(
#                 **scenario
#             )

#     def test_snapshot_saved(self):

#         scenario = (
#             CheckoutBuilder()
#             .with_coupon()
#             .scenario()
#         )

#         order = OrderService.create_online_order(
#             **scenario
#         )

#         assert order.full_name

#         assert order.phone

#         assert order.email

#         assert order.address

#         assert order.city

#         assert order.state

#         assert order.coupon_code == scenario["coupon"].code

#         assert (
#             order.coupon_discount_percent
#             ==
#             scenario["coupon"].discount_percent
#         )

#     def test_total_price(self):

#         scenario = (
#             CheckoutBuilder()
#             .with_quantity(3)
#             .scenario()
#         )

#         order = OrderService.create_online_order(
#             **scenario
#         )

#         item = order.order_items.first()

#         assert order.total_price == (
#             item.price * 3
#         )

#     def test_expire_at_created(self):

#         scenario = (
#             CheckoutBuilder()
#             .with_coupon()
#             .scenario()
#         )

#         order = OrderService.create_online_order(
#             **scenario
#         )

#         assert order.expire_at is not None

#         assert order.is_expired() is False
        
        
import pytest

from django.core.exceptions import ValidationError

from order.services.order import OrderService
from order.models import OrderModel

from shop.constants import ProductStatusType

pytestmark = pytest.mark.django_db


class TestCreateOnlineOrder:

    def test_create_order(
        self,
        user,
        address,
        cart,
        product,
    ):

        cart.add(product, quantity=2)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert isinstance(order, OrderModel)

        order.refresh_from_db()

        assert order.user == user
        assert order.order_items.count() == 1
        assert order.status == order.status.pending

    def test_snapshot_created(
        self,
        user,
        address,
        cart,
        product,
    ):

        cart.add(product)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert order.full_name == user.profile.get_fullname()
        assert order.phone == user.profile.phone_number
        assert order.email == user.email

    def test_address_snapshot(
        self,
        user,
        address,
        cart,
        product,
    ):

        cart.add(product)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert order.address == address.address
        assert order.city == address.city
        assert order.state == address.state
        assert order.zip_code == address.zip_code

    def test_create_items(
        self,
        user,
        address,
        cart,
        product,
    ):

        cart.add(product, quantity=3)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        item = order.order_items.first()

        assert item.quantity == 3
        assert item.product == product

    def test_stock_decreased(
        self,
        user,
        address,
        cart,
        product,
    ):

        old_stock = product.stock

        cart.add(product, quantity=4)

        OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        product.refresh_from_db()

        assert product.stock == old_stock - 4

    def test_coupon_snapshot(
        self,
        user,
        address,
        cart,
        product,
        coupon,
    ):

        cart.add(product)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
            coupon=coupon,
        )

        assert order.coupon == coupon
        assert order.coupon_code == coupon.code
        assert order.coupon_discount_percent == coupon.discount_percent

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

    def test_draft_product(
        self,
        user,
        address,
        cart,
        product,
    ):

        product.status = ProductStatusType.DRAFT
        product.save()

        cart.add(product)

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

    def test_out_of_stock(
        self,
        user,
        address,
        cart,
        product,
    ):

        product.stock = 1
        product.save()

        cart.add(product, quantity=2)

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
        cart,
        product,
        expired_coupon,
    ):

        cart.add(product)

        with pytest.raises(ValidationError):

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
                coupon=expired_coupon,
            )

    def test_expire_time_created(
        self,
        user,
        address,
        cart,
        product,
    ):

        cart.add(product)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert order.expire_at > order.created_date

    def test_event_created(
        self,
        mocker,
        user,
        address,
        cart,
        product,
    ):

        event = mocker.patch(
            "order.services.order.record_order_event"
        )

        cart.add(product)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        event.assert_called_once()

    def test_bulk_create_called(
        self,
        mocker,
        user,
        address,
        cart,
        product,
    ):

        bulk = mocker.patch(
            "order.services.order.OrderItemModel.objects.bulk_create"
        )

        cart.add(product)

        OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        bulk.assert_called_once()
        
# ------------------------------------------------------------------
# Pricing
# ------------------------------------------------------------------


class TestPricing:

    def test_total_price_saved(
        self,
        user,
        address,
        cart,
        product,
    ):
        cart.add(product, quantity=2)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert order.total_price == order.final_price

    def test_item_price_snapshot(
        self,
        user,
        address,
        cart,
        product,
    ):
        cart.add(product)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        item = order.order_items.first()

        assert item.price == product.final_price

    def test_multiple_items_created(
        self,
        user,
        address,
        cart,
        product_factory,
    ):
        p1 = product_factory(price=100)
        p2 = product_factory(price=200)

        cart.add(p1, quantity=2)
        cart.add(p2, quantity=3)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert order.order_items.count() == 2
        
# ------------------------------------------------------------------
# Inventory
# ------------------------------------------------------------------


class TestInventory:

    def test_all_products_updated(
        self,
        user,
        address,
        cart,
        product_factory,
    ):
        p1 = product_factory(stock=10)
        p2 = product_factory(stock=10)

        cart.add(p1, quantity=2)
        cart.add(p2, quantity=3)

        OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        p1.refresh_from_db()
        p2.refresh_from_db()

        assert p1.stock == 8
        assert p2.stock == 7

    def test_stock_snapshot_not_changed(
        self,
        user,
        address,
        cart,
        product,
    ):
        old_price = product.final_price

        cart.add(product)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        product.final_price += 1000
        product.save()

        item = order.order_items.first()

        assert item.price == old_price
        
# ------------------------------------------------------------------
# Policy
# ------------------------------------------------------------------


class TestPolicy:

    def test_policy_called(
        self,
        mocker,
        user,
        address,
        cart,
        product,
    ):
        policy = mocker.patch(
            "order.services.order.OrderPolicy.can_create_order"
        )

        cart.add(product)

        OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        policy.assert_called_once_with(user)

    def test_policy_failure(
        self,
        mocker,
        user,
        address,
        cart,
        product,
    ):
        mocker.patch(
            "order.services.order.OrderPolicy.can_create_order",
            side_effect=ValidationError("boom"),
        )

        cart.add(product)

        with pytest.raises(ValidationError):
            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )
            
# ------------------------------------------------------------------
# Events
# ------------------------------------------------------------------


class TestEvents:

    def test_event_payload(
        self,
        mocker,
        user,
        address,
        cart,
        product,
    ):
        event = mocker.patch(
            "order.services.order.record_order_event"
        )

        cart.add(product)

        order = OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        kwargs = event.call_args.kwargs

        assert kwargs["order"] == order
        assert kwargs["actor"] == user

        payload = kwargs["payload"]

        assert "total_price" in payload
        assert "expire_at" in payload

    def test_event_only_once(
        self,
        mocker,
        user,
        address,
        cart,
        product,
    ):
        event = mocker.patch(
            "order.services.order.record_order_event"
        )

        cart.add(product)

        OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        assert event.call_count == 1
        
# ------------------------------------------------------------------
# Atomicity
# ------------------------------------------------------------------


class TestAtomicity:

    def test_bulk_create_failure_rolls_back(
        self,
        mocker,
        user,
        address,
        cart,
        product,
    ):
        cart.add(product)

        mocker.patch(
            "order.services.order.OrderItemModel.objects.bulk_create",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):
            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

        assert OrderModel.objects.count() == 0

    def test_event_failure_rolls_back(
        self,
        mocker,
        user,
        address,
        cart,
        product,
    ):
        cart.add(product)

        mocker.patch(
            "order.services.order.record_order_event",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):
            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

        assert OrderModel.objects.count() == 0

    def test_stock_rollback(
        self,
        mocker,
        user,
        address,
        cart,
        product,
    ):
        old_stock = product.stock

        cart.add(product, quantity=2)

        mocker.patch(
            "order.services.order.OrderItemModel.objects.bulk_create",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):
            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

        product.refresh_from_db()

        assert product.stock == old_stock
        
# ------------------------------------------------------------------
# Database Behaviour
# ------------------------------------------------------------------


class TestDatabase:

    def test_bulk_create_once(
        self,
        mocker,
        user,
        address,
        cart,
        product_factory,
    ):
        bulk = mocker.patch(
            "order.services.order.OrderItemModel.objects.bulk_create"
        )

        p1 = product_factory()
        p2 = product_factory()

        cart.add(p1)
        cart.add(p2)

        OrderService.create_online_order(
            user=user,
            address=address,
            cart=cart,
        )

        bulk.assert_called_once()

    def test_products_loaded_once(
        self,
        mocker,
        user,
        address,
        cart,
        product,
    ):
        in_bulk = mocker.patch(
            "order.services.order.ProductModel.objects.select_for_update"
        )

        cart.add(product)

        try:
            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )
        except Exception:
            pass

        assert in_bulk.called