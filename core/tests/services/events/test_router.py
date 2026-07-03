# tests/services/events/test_router.py
import pytest

from unittest.mock import Mock

from events.dispatchers.router import dispatch
from events.dispatchers.registry import ROUTES

pytestmark = pytest.mark.django_db


class TestRouter:

    def test_calls_handlers(
        self,
        monkeypatch,
    ):
        first = Mock()
        second = Mock()

        monkeypatch.setitem(
            ROUTES,
            "topic.test",
            (
                first,
                second,
            ),
        )

        event = Mock(topic="topic.test")

        dispatch(event)

        first.assert_called_once_with(event)
        second.assert_called_once_with(event)

    def test_unknown_topic(
        self,
    ):
        dispatch(
            Mock(topic="unknown"),
        )