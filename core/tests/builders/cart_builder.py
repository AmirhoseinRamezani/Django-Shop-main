# tests/builders/cart_builder.py

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

    def for_user(self, user):

        self.user = user

        self.cart.user = user

        self.cart.save(update_fields=["user"])

        return self

    # ----------------------------

    def with_item(
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

            self.with_item()

        return self

    # ----------------------------

    def build(self):

        return self.cart

    # Backward-compatible aliases for older builder callers.
    with_user = for_user
    add = with_item
