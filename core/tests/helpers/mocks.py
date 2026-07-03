# tests/helpers/mocks.py
from unittest.mock import Mock


def fake_gateway(
    authority="AUTH-1",
    payment_url="https://gateway.test/pay",
):

    gateway = Mock()

    gateway.payment_request.return_value = {
        "Authority": authority,
    }

    gateway.generate_payment_url.return_value = (
        payment_url
    )

    return gateway


def fake_dispatcher():

    return Mock()


def fake_webhook():

    return Mock()


def fake_email():

    return Mock()


def fake_telegram():

    return Mock()
