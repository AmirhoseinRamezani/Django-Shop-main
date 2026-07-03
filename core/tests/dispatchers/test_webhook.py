# tests/dispatchers/test_webhook.py
import pytest

from unittest.mock import patch

from events.dispatchers.webhook import send_webhook_event


pytestmark = pytest.mark.django_db


@patch("events.clients.webhook.WebhookClient.post")
def test_webhook(client):

    class Event:

        topic = "order.paid"

        payload = {
            "order_id": 1,
        }

    send_webhook_event(Event())

    client.assert_called_once()