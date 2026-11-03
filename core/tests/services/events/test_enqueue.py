# tests/events/test_enqueue.py
import pytest
from django.db import transaction

from events.models import OutboxEvent
from events.services.enqueue import publish_event


pytestmark = pytest.mark.django_db(transaction=True)

def test_publish_event_requires_atomic_transaction():
    with pytest.raises(RuntimeError, match=r"transaction\.atomic"):
        publish_event(topic="user.otp", payload={"email": "a@test.com"})

def test_publish_event():
    with transaction.atomic():
        event = publish_event(
            topic="user.otp",
            payload={"email": "a@test.com", "code": "123456"},
        )
    
    assert OutboxEvent.objects.count() == 1
    assert event.topic == "user.otp"