# # tests/builders/cart.py

# from tests.factories.cart import (
#     CartFactory,
#     CartItemFactory,
# )


# class CartBuilder:
#     """
#     Builder only creates carts.

#     It never creates products.
#     It only assembles a cart.
#     """

#     def __init__(self):
#         self.user = None
#         self.items = []

#     def for_user(self, user):
#         self.user = user
#         return self

#     def with_item(
#         self,
#         product,
#         quantity=1,
#     ):
#         self.items.append(
#             (product, quantity)
#         )
#         return self

#     def build(self):

#         assert self.user is not None
#         cart = CartFactory(
#             user=self.user,
#         )

#         for product, quantity in self.items:

#             CartItemFactory(
#                 cart=cart,
#                 product=product,
#                 quantity=quantity,
#             )

#         return cart
from cart.models import CartModel, CartItemModel

from tests.factories.accounts import UserFactory
from tests.factories.shop import ProductFactory


class CartBuilder:

    def __init__(self):

        self.user = UserFactory()

        self.cart = CartModel.objects.create(
            user=self.user
        )

    # ----------------------------

    def with_user(self, user):

        self.user = user

        self.cart.user = user

        self.cart.save(update_fields=["user"])

        return self

    # ----------------------------

    def add(
        self,
        product=None,
        qty=1,
    ):

        product = product or ProductFactory()

        CartItemModel.objects.create(
            cart=self.cart,
            product=product,
            quantity=qty,
        )

        return self

    # ----------------------------

    def many(self, count=5):

        for _ in range(count):

            self.add()

        return self

    # ----------------------------

    def build(self):

        return self.cart
