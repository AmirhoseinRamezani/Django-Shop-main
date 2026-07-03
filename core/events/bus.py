
from events.services.enqueue import publish_event


def publish(*, topic, payload):

    return publish_event(
        topic=topic,
        payload=payload,
    )