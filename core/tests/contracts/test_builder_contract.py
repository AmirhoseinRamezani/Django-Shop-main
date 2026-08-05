# tests/contracts/test_builder_contract.py
import pytest


pytestmark = pytest.mark.django_db


def test_builders_importable():

    from tests.builders.order_builder import OrderBuilder
    from tests.builders.payment_builder import PaymentBuilder
    from tests.builders.cart_builder import CartBuilder

    assert OrderBuilder
    assert PaymentBuilder
    assert CartBuilder