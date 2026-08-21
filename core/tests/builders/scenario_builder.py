# tests/builders/scenario_builder.py
from tests.builders import (
    UserBuilder,
    ProductBuilder,
    CartBuilder,
    OrderBuilder,
    PaymentBuilder,
)

from tests.factories.shop import (
    CouponFactory,
)


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