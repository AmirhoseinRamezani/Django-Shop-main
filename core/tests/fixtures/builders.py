import pytest

from tests.builders import (
    OrderBuilder,
    PaymentBuilder,
    CartBuilder,
    OutboxBuilder,
    EventBuilder,
)


@pytest.fixture
def order_builder():
    return OrderBuilder()


@pytest.fixture
def payment_builder():
    return PaymentBuilder()


@pytest.fixture
def cart_builder():
    return CartBuilder()


@pytest.fixture
def outbox_builder():
    return OutboxBuilder()


@pytest.fixture
def event_builder():
    return EventBuilder