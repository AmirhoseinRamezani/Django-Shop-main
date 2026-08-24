# tests/fixtures/events.py

import pytest


from tests.factories.events import (
    OutboxEventFactory,
)

@pytest.fixture
def event_factory():

    return OutboxEventFactory

@pytest.fixture
def pending_event(db):

    return OutboxEventFactory()

@pytest.fixture
def processed_event(db):

    return OutboxEventFactory(
        processed=True
    )

@pytest.fixture
def failed_event(db):

    return OutboxEventFactory(
        failed=True
    )