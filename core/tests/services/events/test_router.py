# tests/services/events/test_router.py
import pytest
from unittest.mock import Mock

from events.dispatchers.router import (
    UnknownTopicError,
    dispatch,
)

def test_calls_handlers(monkeypatch):
    first = Mock()
    second = Mock()
    import events.dispatchers.router as router

    monkeypatch.setitem(router.ROUTES, "topic.test", (first, second))
    event = Mock(topic="topic.test")

    dispatch(event)

    first.assert_called_once_with(event)
    second.assert_called_once_with(event)


def test_explicit_noop_topic_is_accepted():
    dispatch(Mock(topic="order.pending"))


def test_unknown_topic_is_rejected():
    with pytest.raises(UnknownTopicError, match="No dispatch route"):
        dispatch(Mock(topic="order.typo"))