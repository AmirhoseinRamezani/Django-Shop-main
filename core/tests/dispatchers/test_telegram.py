# tests/dispatchers/test_telegram.py
import pytest

from unittest.mock import patch

from events.dispatchers.telegram import send_telegram_event


pytestmark = pytest.mark.django_db

@patch("events.dispatchers.telegram.TelegramClient.send_message")
def test_order_paid(message):

    class Event:

        topic = "order.paid"

        payload = {
            "order_id": 10,
            "amount": "250000",
        }

    send_telegram_event(Event())

    message.assert_called_once()


@patch("events.dispatchers.telegram.TelegramClient.send_photo")
def test_product_published(photo):

    class Event:

        topic = "product.published"

        payload = {
            "name": "MacBook",

            "price": "100",

            "caption": "New",

            "url": "https://test.com/image.jpg",
        }

    send_telegram_event(Event())

    photo.assert_called_once()