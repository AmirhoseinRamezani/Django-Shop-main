# # tests/builders/checkout_builder.py

# from tests.builders.base import Builder

# from tests.factories.accounts import UserFactory

# from tests.factories.cart import (
#     CartFactory,
#     CartItemFactory,
# )

# from tests.factories.shop import (
#     AddressFactory,
#     ProductFactory,
# )


# class CheckoutBuilder(Builder):
#     """
#     Builder used for OrderService.create_online_order()

#     Example:

#         kwargs = (
#             CheckoutBuilder()
#             .with_item(quantity=2)
#             .with_coupon(expired=True)
#             .build()
#         )

#         order = OrderService.create_online_order(**kwargs)
#     """

#     def __init__(self):
#         super().__init__()

#         # self.user = UserFactory()

#         # self.cart = CartFactory(
#         #     user=self.user,
#         # )

#         # self.address = AddressFactory(
#         #     user=self.user,
#         # )

#     # -------------------------
#     # Override user
#     # -------------------------

#     def for_user(self, user):

#         self.user = user

#         self.cart.user = user
#         self.cart.save(update_fields=["user"])

#         self.address.user = user
#         self.address.save(update_fields=["user"])

#         return self

#     # -------------------------
#     # Cart
#     # -------------------------

#     def with_item(
#         self,
#         product=None,
#         quantity=1,
#         replace=False,
#         **traits,
#     ):

#         if product is None:
#             product = ProductFactory(**traits)

#         if replace:
#             self.cart.cart_items.all().delete()
            
#         CartItemFactory(
#             # cart=self.cart,
#             product=product,
#             quantity=quantity,
#         )

#         return self

#     def with_items(self, count=2):

#         self.cart.cart_items.all().delete()
        
#         for _ in range(count):
#             self.with_item()

#         return self

#     # -------------------------
#     # Address
#     # -------------------------

#     def with_address(self, address):

#         self.address = address

#         return self

#     # -------------------------
#     # Build kwargs
#     # -------------------------

#     def build(self):

#         if not self.cart.cart_items.exists():
#             raise RuntimeError(
#                 "CheckoutBuilder created an empty cart."
#             )
            
#         data = {
#             "user": self.user,
#             "cart": self.cart,
#             "address": self.address,
#         }

#         data.update(self.kwargs)

#         return data

from .scenario_builder import ScenarioBuilder


class CheckoutBuilder(ScenarioBuilder):
    """
    Checkout Scenario
    """
    pass