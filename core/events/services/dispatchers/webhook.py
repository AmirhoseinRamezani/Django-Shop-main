# events/services/dispatchers/webhook.py
import requests

def send_webhook_event(event):
    # Example
    requests.post(
        "https://partner.example/webhook",
        json={
            "topic": event.topic,
            "payload": event.payload,
        },
        timeout=3,
    )
