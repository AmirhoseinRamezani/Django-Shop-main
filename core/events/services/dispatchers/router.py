# events/services/dispatchers/router.py
from events.services.dispatchers.telegram import send_telegram_event
from events.services.dispatchers.email import send_email_event
from events.services.dispatchers.webhook import send_webhook_event


def dispatch(event):
    topic = event.topic

    if topic.startswith("user."):
        send_email_event(event)
    # order.*
    elif topic.startswith("order."):
        send_email_event(event)
        send_telegram_event(event)
        send_webhook_event(event)

    # product.*
    elif topic.startswith("product."):
        send_telegram_event(event)

    # unknown topic → ignore safely
    
