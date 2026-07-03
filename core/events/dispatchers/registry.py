# events/dispatchers/registry.py

from events.dispatchers.email import send_email_event
from events.dispatchers.telegram import send_telegram_event
from events.dispatchers.webhook import send_webhook_event

ROUTES = {

    "user.otp": (
        send_email_event,
    ),

    "order.created": (
        send_email_event,
    ),

    "order.paid": (
        send_email_event,
        send_telegram_event,
        send_webhook_event,
    ),

    "order.cancelled": (
        send_email_event,
        send_webhook_event,
    ),

    "coupon.used": (
        send_email_event,
        send_webhook_event,
    ),

    "product.published": (
        send_telegram_event,
    ),
}