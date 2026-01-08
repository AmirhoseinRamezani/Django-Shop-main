# events/services/enqueue.py

from events.models.outbox import OutboxEvent

def publish_event(*, topic: str, payload: dict):
    """
    MUST be called inside a transaction.
    """
    OutboxEvent.objects.create(
        topic=topic,
        payload=payload
    )
