from events.services.dispatchers.telegram import send_telegram_event
from events.services.dispatchers.email import send_email_event
from events.services.dispatchers.webhook import send_webhook_event


def dispatch(outbox_event):
    topic = outbox_event.topic

    # order.*
    if topic.startswith("order."):
        send_telegram_event(outbox_event)
        send_email_event(outbox_event)
        send_webhook_event(outbox_event)

    # product.*
    elif topic.startswith("product."):
        send_telegram_event(outbox_event)

    else:
        # unknown topic → ignore safely
        return
