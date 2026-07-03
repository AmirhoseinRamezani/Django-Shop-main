# tests/contracts/test_builder_contract.py
import pytest


pytestmark = pytest.mark.django_db


def test_builders_importable():

    from tests.builders.order import OrderBuilder
    from tests.builders.payment import PaymentBuilder
    from tests.builders.cart import CartBuilder

    assert OrderBuilder
    assert PaymentBuilder
    assert CartBuilder