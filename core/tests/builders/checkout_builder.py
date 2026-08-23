# tests/builders/checkout_builder.py

from tests.builders.cart_builder import CartBuilder
from tests.builders.order_builder import OrderBuilder
from tests.builders.user_builder import UserBuilder


class CheckoutBuilder:
    """
    Builder responsible for assembling checkout state context.
    """

    def __init__(self):
        self._user_builder = UserBuilder()
        self._cart_builder = CartBuilder()
        self._order_builder = OrderBuilder()

    def for_user(self, user):
        self._user_builder._attrs['user'] = user
        self._cart_builder.for_user(user)
        self._order_builder.for_user(user)
        return self

    def build(self):
        user = self._user_builder.build()
        cart = self._cart_builder.for_user(user).build()
        order = self._order_builder.for_user(user).build()
        return {
            "user": user,
            "cart": cart,
            "order": order,
        }