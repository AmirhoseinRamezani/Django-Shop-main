# events/services/dispatchers/base.py
"""
Single entry point for dispatching Outbox events.

This layer decides WHICH channel should handle the event.
"""

from events.services.dispatchers import email, telegram
    
def dispatch(event):
    """
    Route event to appropriate dispatcher based on topic.
    """
    # Email related events
    if event.topic.startswith("user.") or event.topic.startswith("order."):
        email.send_email_event(event)
    
    # Telegram related events
    if event.topic == "order.paid":
        telegram.send_order_paid(event.payload)
