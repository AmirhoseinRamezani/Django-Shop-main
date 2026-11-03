import pytest
import requests

from events.clients.webhook import WebhookClient


def test_webhook_client_posts_event_and_idempotency_key(mocker):
    response = mocker.Mock()
    session = mocker.patch("events.clients.webhook.requests.Session")
    session.return_value.post.return_value = response

    client = WebhookClient("https://partner.example/events", timeout=3)
    result = client.post(
        {"order_id": 42},
        "order.paid",
        event_id="event-uuid",
    )

    session.return_value.post.assert_called_once_with(
        "https://partner.example/events",
        json={"topic": "order.paid", "payload": {"order_id": 42}},
        headers={
            "X-Event-Topic": "order.paid",
            "Idempotency-Key": "event-uuid",
        },
        timeout=3,
    )
    response.raise_for_status.assert_called_once_with()
    assert result is response


def test_webhook_client_propagates_http_failure(mocker):
    session = mocker.patch("events.clients.webhook.requests.Session")
    response = session.return_value.post.return_value
    response.raise_for_status.side_effect = requests.HTTPError("bad gateway")

    client = WebhookClient("https://partner.example/events")
    with pytest.raises(requests.HTTPError):
        client.post({}, "order.paid")


@pytest.mark.parametrize("timeout", [0, -1, True])
def test_webhook_client_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="timeout"):
        WebhookClient("https://partner.example/events", timeout=timeout)