
from __future__ import annotations

from events.dispatchers.registry import NOOP_TOPICS, ROUTES


class UnknownTopicError(LookupError):
    """Raised when an event topic has no explicit dispatch policy."""


class DispatchError(RuntimeError):
    """Raised after every registered handler has been attempted."""

    def __init__(self, topic: str, failures: list[Exception]):
        self.topic = topic
        self.failures = tuple(failures)

        details = "; ".join(
            f"{type(exc).__name__}: {exc}"
            for exc in failures
        )
        super().__init__(
            f"Dispatch for topic {topic!r} failed: {details}"
        )


def dispatch(event) -> None:
    handlers = ROUTES.get(event.topic)

    if handlers is None:
        if event.topic in NOOP_TOPICS:
            return

        raise UnknownTopicError(
            f"No dispatch route or explicit no-op policy "
            f"for topic {event.topic!r}."
        )

    failures = []

    for handler in handlers:
        try:
            handler(event)
        except Exception as exc:
            failures.append(exc)

    if failures:
        raise DispatchError(event.topic, failures) from failures[0]