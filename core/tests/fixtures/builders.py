# tests/fixtures/builders.py
import pytest

from tests.builders.order_builder import OrderScenarioBuilder
from tests.builders.cart_builder import CartBuilder
from tests.builders.product_builder import ProductBuilder
from tests.builders.payment_builder import PaymentScenarioBuilder
from tests.builders.user_builder import UserBuilder
from tests.builders.coupon_builder import CouponBuilder


@pytest.fixture
def order_builder():
    return OrderScenarioBuilder()

@pytest.fixture
def cart_builder():
    return CartBuilder()

@pytest.fixture
def payment_builder():
    return PaymentScenarioBuilder()

@pytest.fixture
def product_builder():
    return ProductBuilder()

@pytest.fixture
def user_builder():
    return UserBuilder()

@pytest.fixture
def coupon_builder():
    return CouponBuilder()
