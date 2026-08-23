# tests/factories/events.py

import factory

from tests.factories.base import BaseFactory

from events.models import (
    OutboxEvent,
    OutboxStatus,
)

class OutboxEventFactory(BaseFactory):

    class Meta:
        model = OutboxEvent

    topic = factory.Sequence(
        lambda n: f"order.created.{n}"
    )

    payload = factory.LazyFunction(
        lambda: {
            "order_id": 1,
            "user_id": 1,
            "amount": "100000",
        }
    )

    status = OutboxStatus.pending
    retry_count = 0
    last_error = None

    class Params:

        processed = factory.Trait(
            status=OutboxStatus.processed,
        )

        failed = factory.Trait(
            status=OutboxStatus.failed,
            retry_count=3,
            last_error="Gateway timeout",
        )

        retryable = factory.Trait(
            status=OutboxStatus.pending,
            retry_count=1,
        )