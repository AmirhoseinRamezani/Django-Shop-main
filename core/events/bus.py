from django.db import transaction
from events.services.enqueue import publish_event


def publish(*, topic: str, payload: dict):
    # Nested atomic blocks become savepoints when a domain transaction exists.
    with transaction.atomic():
        return publish_event(topic=topic, payload=payload)