# # tests/factories/events.py
# import factory

# from tests.base import BaseFactory

# from events.models.outbox import (
#     OutboxEvent,
#     OutboxStatus,
# )


# class OutboxEventFactory(BaseFactory):

#     class Meta:
#         model = OutboxEvent

#     topic = "user.otp"

#     payload = {
#         "email": "user@example.com",
#         "code": "123456",
#     }

#     status = OutboxStatus.pending

#     retry_count = 0

#     last_error = ""

#     class Params:

#         processed = factory.Trait(
#             status=OutboxStatus.processed,
#         )

#         failed = factory.Trait(
#             status=OutboxStatus.failed,
#             retry_count=5,
#         )

#         order_paid = factory.Trait(
#             topic="order.paid",
#             payload={
#                 "order_id": 1,
#                 "amount": "100000",
#                 "email": "user@example.com",
#             },
#         )


# # OutboxEventFactory
# # OrderEventFactory

import factory

from django.utils import timezone

from tests.base import BaseFactory

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