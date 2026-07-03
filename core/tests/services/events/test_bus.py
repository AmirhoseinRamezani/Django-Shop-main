# tests/services/events/test_bus.py
import pytest

from unittest.mock import patch

from events.bus import publish

pytestmark = pytest.mark.django_db


@patch("events.bus.publish_event")
def test_publish(mock_publish):

    publish(
        topic="user.otp",
        payload={
            "email": "a@test.com",
        },
    )

    mock_publish.assert_called_once_with(
        topic="user.otp",
        payload={
            "email": "a@test.com",
        },
    )