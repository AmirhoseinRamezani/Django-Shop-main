import inspect

import pytest


pytestmark = pytest.mark.django_db


def test_builders_importable():

    from tests.builders import (
        AddressBuilder,
        CartBuilder,
        OrderBuilder,
        PaymentBuilder,
    )

    assert OrderBuilder
    assert PaymentBuilder
    assert CartBuilder
    assert AddressBuilder


def test_builder_compatibility_contract():
    from tests.builders.cart_builder import CartBuilder
    from tests.builders.order_builder import OrderBuilder, OrderScenarioBuilder
    from tests.builders.payment_builder import PaymentBuilder, PaymentScenarioBuilder

    assert OrderBuilder is OrderScenarioBuilder
    assert PaymentBuilder is PaymentScenarioBuilder
    assert hasattr(OrderBuilder, "pending")
    assert hasattr(PaymentBuilder, "for_order")
    assert hasattr(PaymentBuilder, "success")
    assert "quantity" in inspect.signature(CartBuilder.with_item).parameters
    assert hasattr(CartBuilder, "add_many")
