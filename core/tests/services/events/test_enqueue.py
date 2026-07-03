# tests/events/test_enqueue.py
import pytest

from events.models import OutboxEvent
from events.services.enqueue import publish_event


pytestmark = pytest.mark.django_db


def test_publish_event():

    publish_event(
        topic="user.otp",
        payload={
            "email": "a@test.com",
            "code": "123456",
        },
    )

    assert OutboxEvent.objects.count() == 1

    event = OutboxEvent.objects.first()

    assert event.topic == "user.otp"