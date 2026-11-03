from __future__ import annotations
from events.dispatchers.registry import NOOP_TOPICS, ROUTES


class UnknownTopicError(LookupError):
    """Raised when an event topic has no explicit dispatch policy."""


def dispatch(event) -> None:
    """Dispatch an event using an explicit route or explicit no-op policy."""

    handlers = ROUTES.get(event.topic)
    if handlers is not None:
        for handler in handlers:
            handler(event)
        return

    if event.topic in NOOP_TOPICS:
        return

    raise UnknownTopicError(
        f"No dispatch route or explicit no-op policy for topic {event.topic!r}."
    )