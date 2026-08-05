# # tests/fixtures/builders.py
# import pytest

# from tests.builders import (
#     OrderBuilder,
#     PaymentBuilder,
#     CartBuilder,
#     OutboxBuilder,
#     EventBuilder,
#     CheckoutBuilder,
# )


# @pytest.fixture
# def order_builder():
#     return OrderBuilder()


# @pytest.fixture
# def payment_builder():
#     return PaymentBuilder()


# @pytest.fixture
# def cart_builder():
#     return CartBuilder()


# @pytest.fixture
# def outbox_builder():
#     return OutboxBuilder()


# @pytest.fixture
# def event_builder():
#     return EventBuilder

# @pytest.fixture
# def checkout_builder():
#     return CheckoutBuilder()

import pytest

from tests.builders.order_builder import OrderBuilder
from tests.builders.cart_builder import CartBuilder
from tests.builders.product_builder import ProductBuilder
from tests.builders.payment_builder import PaymentBuilder
from tests.builders.user_builder import UserBuilder
from tests.builders.coupon_builder import CouponBuilder


@pytest.fixture
def order_builder():
    return OrderBuilder()


@pytest.fixture
def cart_builder():
    return CartBuilder()


@pytest.fixture
def payment_builder():
    return PaymentBuilder()


@pytest.fixture
def product_builder():
    return ProductBuilder()


@pytest.fixture
def user_builder():
    return UserBuilder()


@pytest.fixture
def coupon_builder():
    return CouponBuilder()
