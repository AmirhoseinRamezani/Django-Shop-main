from events.dispatchers.email import send_email_event
from events.dispatchers.webhook import send_webhook_event

# Only integrations with a real, failure-reporting transport are registered.
# Add a destination only after its client raises on delivery failure and
# supports idempotency using the stable OutboxEvent.event_id.
ROUTES = {

    "user.otp": (
        send_email_event,
    ),

    "order.created": (
        send_email_event,
    ),

    "order.paid": (
        send_email_event,
        send_webhook_event,
    ),

    "order.cancelled": (send_webhook_event,),

    "coupon.used": (
        send_email_event,
        send_webhook_event,
    ),
}
# Persisted domain events with no outbound subscription in this deployment.
# This is deliberately separate from ROUTES: unknown/misspelled topics fail.
NOOP_TOPICS = frozenset({
    "order.pending",
    "order.payment_started",
    "order.failed",
    "order.processing",
    "order.shipped",
    "order.delivered",
    "order.return_requested",
    "order.returned",
    "order.expired",
    "order.refunded",
    "order.admin_note",
    "product.published",  # Telegram transport is not implemented yet.
})