# tests/builders/order_builder.py
from tests.builders.base import Builder

from tests.factories.order import (
    OrderFactory,
    OrderItemFactory,
)


class OrderBuilder(Builder):

    def __init__(self):

        super().__init__()

        self.items = []

    def for_user(self, user):

        self.kwargs["user"] = user

        return self

    def with_coupon(self, coupon):

        self.kwargs["coupon"] = coupon

        return self

    def paid(self):

        self.kwargs["paid"] = True

        return self

    def processing(self):

        self.kwargs["processing"] = True

        return self

    def cancelled(self):

        self.kwargs["cancelled"] = True

        return self

    def with_item(
        self,
        product,
        quantity=1,
        price=None,
    ):

        self.items.append(
            {
                "product": product,
                "quantity": quantity,
                "price": price,
            }
        )

        return self

    def build(self):

        order = OrderFactory(
            **self.kwargs
        )

        for item in self.items:

            OrderItemFactory(
                order=order,
                product=item["product"],
                quantity=item["quantity"],
                price=item["price"]
                or item["product"].final_price,
            )

        return order