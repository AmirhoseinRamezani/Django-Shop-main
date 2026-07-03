# tests/builders/cart.py
from tests.builders.base import Builder

from tests.factories.cart import (
    CartFactory,
    CartItemFactory,
)


class CartBuilder(Builder):

    def __init__(self):

        super().__init__()

        self.items = []

    def for_user(self, user):

        self.kwargs["user"] = user

        return self

    def with_item(
        self,
        product,
        quantity=1,
    ):

        self.items.append(
            (
                product,
                quantity,
            )
        )

        return self

    def build(self):

        cart = CartFactory(
            **self.kwargs
        )

        for product, quantity in self.items:

            CartItemFactory(
                cart=cart,
                product=product,
                quantity=quantity,
            )

        return cart