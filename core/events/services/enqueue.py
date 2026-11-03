# events/services/enqueue.py
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from events.models.outbox import OutboxEvent

def publish_event(*, topic: str, payload: dict, using: str = "default") -> OutboxEvent:
    """
    Persist an event in the caller's transaction.

    Call this from the same atomic transaction as the domain-state change.
    The guard prevents accidental non-atomic publication.
    """
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 100:
        raise ValidationError({"topic": "A non-empty topic of at most 100 characters is required."})
    if not isinstance(payload, dict):
        raise ValidationError({"payload": "Outbox payload must be a JSON object."})
    if not connections[using].in_atomic_block:
        raise RuntimeError("publish_event() must run inside transaction.atomic().")

    return OutboxEvent.objects.using(using).create(
        topic=topic.strip(),
        payload=payload,
    )
