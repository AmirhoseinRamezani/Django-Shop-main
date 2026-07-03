import pytest

from tests.factories.payment import (
    PaymentFactory,
)


@pytest.fixture
def payment(db, order):
    return PaymentFactory(order=order)


@pytest.fixture
def successful_payment(db, order):
    return PaymentFactory(
        order=order,
        success=True,
    )


@pytest.fixture
def consumed_payment(db, order):
    return PaymentFactory(
        order=order,
        consumed=True,
    )

@pytest.fixture
def payment_factory():
    return PaymentFactory