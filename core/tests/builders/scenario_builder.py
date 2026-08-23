# tests/builders/scenario_builder.py
from tests.builders.cart_builder import CartBuilder
from tests.builders.coupon_builder import CouponBuilder
from tests.builders.order_builder import OrderBuilder
from tests.builders.payment_builder import PaymentBuilder
from tests.builders.product_builder import ProductBuilder
from tests.builders.user_builder import UserBuilder

from tests.factories.shop import (
    CouponFactory,
)

class ScenarioBuilder:
    """
    High-level test scenario orchestration builder.
    """

    def __init__(self):
        self.user_builder = UserBuilder()
        self.cart_builder = CartBuilder()
        self.order_builder = OrderBuilder()
        self.payment_builder = PaymentBuilder()
        self.product_builder = ProductBuilder()
        self.coupon_builder = CouponBuilder()

    def with_user(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self.user_builder, f"with_{k}"):
                getattr(self.user_builder, f"with_{k}")(v)
        return self

    def build(self):
        user = self.user_builder.build()
        return {
            "user": user,
            "cart": self.cart_builder.for_user(user).build(),
            "order": self.order_builder.for_user(user).build(),
        }

class OrderScenario:

    def __init__(self):

        self.user = None
        self.products = []
        self.cart = None
        self.order = None
        self.payment = None
        self.coupon = None

    def with_user(self):

        self.user = (
            UserBuilder()
            .verified()
            .build()
        )

        return self

    def with_products(self, count=1):

        self.products = []

        for _ in range(count):

            self.products.append(
                ProductBuilder()
                .stock(100)
                .build()
            )

        return self

    def with_coupon(self, percent=10):

        self.coupon = CouponFactory(
            discount_percent=percent
        )

        return self

    def with_stock(self, stock):

        for p in self.products:
            p.stock = stock
            p.save(update_fields=["stock"])

        return self

    def checkout(self):

        self.cart = (
            CartBuilder(self.user)
            .add_many(self.products)
            .build()
        )

        self.order = (

            OrderBuilder()
            .with_user(self.user)
            .with_cart(self.cart)
            .with_address()
            .with_coupon(self.coupon)
            .create()
        )

        return self

    def pay(self):

        self.payment = (

            PaymentBuilder(self.order)
            .start()
            .build()
        )

        return self

    def verify(self):

        PaymentBuilder(
            self.order
        ).start()

        PaymentBuilder(
            self.order
        ).verify()

        self.payment = self.order.last_payment()

        return self