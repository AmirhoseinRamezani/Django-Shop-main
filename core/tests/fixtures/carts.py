# tests/fixtures/carts.py
import pytest

from tests.factories.cart import (
    CartFactory,
    CartItemFactory,
)

@pytest.fixture
def cart(db, user):
    return CartFactory(user=user)


@pytest.fixture
def cart_item(db, cart):
    return CartItemFactory(cart=cart)

@pytest.fixture
def cart_with_two_items(
    cart,
    product,
    second_product,
):
    cart.add(product, quantity=2)
    cart.add(second_product, quantity=3)
    return cart
