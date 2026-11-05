# tests/dispatchers/test_webhook.py
import uuid
import pytest

from unittest.mock import patch

from events.dispatchers.webhook import send_webhook_event


pytestmark = pytest.mark.django_db


@patch("events.clients.webhook.WebhookClient.post")
def test_webhook(client):

    class Event:

        topic = "order.paid"
        event_id = uuid.UUID("f8a3d4b1-2c6e-4d91-9a70-5b8e2c1f6a43")

        payload = {
            "order_id": 1,
        }

    send_webhook_event(Event())

    client.assert_called_once_with(
        Event.payload,
        Event.topic,
        event_id=str(Event.event_id),
    )