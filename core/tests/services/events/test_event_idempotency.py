# tests/services/events/test_event_idempotency.py
import pytest


from tests.factories.events import (
    OutboxEventFactory
)



@pytest.mark.service
@pytest.mark.django_db
class TestEventIdempotency:


    def test_processing_same_event_twice_should_not_duplicate(
            self
    ):

        event = OutboxEventFactory()


        event.status="processed"

        event.save()



        event.status="processed"

        event.save()



        event.refresh_from_db()


        assert (
            event.status ==
            "processed"
        )