import pytest

from tests.factories.events import (
    OutboxEventFactory,
)

@pytest.fixture
def outbox_event(db):
    return OutboxEventFactory()


@pytest.fixture
def paid_outbox_event(db):
    return OutboxEventFactory(
        order_paid=True,
    )
