# tests/factories/cart.py
import factory

from tests.base import BaseFactory

from cart.models import (
    CartModel,
    CartItemModel,
)

from tests.factories.accounts import UserFactory
from tests.factories.shop import ProductFactory


class CartFactory(BaseFactory):

    class Meta:
        model = CartModel

    user = factory.SubFactory(UserFactory)


class CartItemFactory(BaseFactory):

    class Meta:
        model = CartItemModel

    cart = factory.SubFactory(CartFactory)

    product = factory.SubFactory(ProductFactory)

    quantity = 1

    class Params:

        two = factory.Trait(
            quantity=2,
        )

        many = factory.Trait(
            quantity=5,
        )

# CartFactory
# CartItemFactory