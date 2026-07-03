import pytest
from tests.factories.order import (
    OrderFactory,
    OrderItemFactory,
    OrderWithItemsFactory,
)


@pytest.fixture
def order(db, user):
    return OrderFactory(user=user)

@pytest.fixture
def paid_order():
    return OrderFactory(paid=True)


@pytest.fixture
def processing_order():
    return OrderFactory(processing=True)


@pytest.fixture
def shipped_order():
    return OrderFactory(shipped=True)


@pytest.fixture
def delivered_order():
    return OrderFactory(delivered=True)


@pytest.fixture
def failed_order():
    return OrderFactory(failed=True)


@pytest.fixture
def cancelled_order():
    return OrderFactory(cancelled=True)


@pytest.fixture
def returned_order():
    return OrderFactory(returned=True)


@pytest.fixture
def return_requested_order():
    return OrderFactory(return_requested=True)


@pytest.fixture
def refunded_order():
    return OrderFactory(refunded=True)


@pytest.fixture
def order_with_items():
    return OrderWithItemsFactory()