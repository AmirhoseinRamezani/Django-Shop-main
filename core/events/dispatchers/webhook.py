# events/dispatchers/webhook.py
from django.conf import settings

from events.clients.webhook import (
    WebhookClient,
)


def send_webhook_event(event):

    endpoint = getattr(
        settings,
        "PARTNER_WEBHOOK",
        "http://localhost/webhook",
    )

    client = WebhookClient(endpoint)

    client.post({

        "topic": event.topic,

        "payload": event.payload,

    })
