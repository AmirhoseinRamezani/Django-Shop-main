# tests/dispatchers/test_email.py
import pytest

from unittest.mock import patch
from events.dispatchers.email import send_email_event


pytestmark = pytest.mark.django_db


class Event:

    topic = "user.otp"

    payload = {
        "email": "a@test.com",
        "code": "123456",
    }

@patch("events.dispatchers.email.EmailClient.send")
def test_send_otp_email(client):

    send_email_event(Event())

    client.assert_called_once()


@patch("events.dispatchers.email.EmailClient.send")
def test_unknown_topic(client):

    class Unknown:

        topic = "unknown"

        payload = {}

    send_email_event(Unknown())

    client.assert_not_called()