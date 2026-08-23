# tests/builders/cart.py

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
