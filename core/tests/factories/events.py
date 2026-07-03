# tests/factories/events.py
import factory

from tests.base import BaseFactory

from events.models.outbox import (
    OutboxEvent,
    OutboxStatus,
)


class OutboxEventFactory(BaseFactory):

    class Meta:
        model = OutboxEvent

    topic = "user.otp"

    payload = {
        "email": "user@example.com",
        "code": "123456",
    }

    status = OutboxStatus.pending

    retry_count = 0

    last_error = ""

    class Params:

        processed = factory.Trait(
            status=OutboxStatus.processed,
        )

        failed = factory.Trait(
            status=OutboxStatus.failed,
            retry_count=5,
        )

        order_paid = factory.Trait(
            topic="order.paid",
            payload={
                "order_id": 1,
                "amount": "100000",
                "email": "user@example.com",
            },
        )


# OutboxEventFactory
# OrderEventFactory