
import pytest

from django.core.exceptions import ValidationError

from events.dispatchers.email import (
    send_email_event,
    send_order_created,
    send_order_paid_email,
)
from tests.factories.accounts import UserFactory


pytestmark = pytest.mark.django_db


def test_order_created_resolves_recipient_from_user_id(mocker):
    user = UserFactory(email="buyer@example.com")
    send = mocker.patch("events.dispatchers.email.EmailClient.send")

    class Event:
        topic = "order.created"
        payload = {
            "order_id": 10,
            "user_id": user.pk,
        }

    send_email_event(Event())

    send.assert_called_once_with(
        subject="ثبت سفارش",
        message="سفارش شما ثبت شد.",
        recipients=["buyer@example.com"],
    )


def test_order_paid_resolves_recipient_from_user_id(mocker):
    user = UserFactory(email="buyer@example.com")
    send = mocker.patch("events.dispatchers.email.EmailClient.send")

    send_order_paid_email(
        {
            "order_id": 42,
            "user_id": user.pk,
            "amount": "100000",
        }
    )

    send.assert_called_once_with(
        subject="پرداخت موفق",
        message="پرداخت سفارش 42 با موفقیت انجام شد.",
        recipients=["buyer@example.com"],
    )


def test_explicit_email_takes_precedence_over_user_id(mocker):
    user = UserFactory(email="account@example.com")
    send = mocker.patch("events.dispatchers.email.EmailClient.send")

    send_order_created(
        {
            "user_id": user.pk,
            "email": "snapshot@example.com",
        }
    )

    assert send.call_args.kwargs["recipients"] == [
        "snapshot@example.com"
    ]


def test_missing_recipient_is_a_delivery_failure():
    with pytest.raises(ValidationError, match="user_id"):
        send_order_created({"order_id": 10})


def test_unknown_email_topic_remains_unhandled(mocker):
    send = mocker.patch("events.dispatchers.email.EmailClient.send")

    class Event:
        topic = "unknown.topic"
        payload = {}

    send_email_event(Event())

    send.assert_not_called()