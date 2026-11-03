from django.conf import settings

from events.clients.webhook import WebhookClient


def send_webhook_event(event):
    endpoint = getattr(settings, "PARTNER_WEBHOOK", None)
    if not endpoint:
        raise RuntimeError("PARTNER_WEBHOOK is not configured.")

    client = WebhookClient(endpoint)
    client.post(
        event.payload,
        event.topic,
        event_id=str(event.event_id),
    )