from unittest.mock import Mock

import pytest
import requests

from payment.exceptions import (
    PaymentGatewayAuthenticationError,
    PaymentGatewayInvalidResponseError,
    PaymentGatewayUnavailableError,
    PaymentGatewayTimeoutError,
)
from payment.gateways.zarinpal import ZarinPalGateway


pytestmark = pytest.mark.django_db


def gateway():
    return ZarinPalGateway(
        merchant_id="test-merchant",
        sandbox=True,
        session=Mock(),
    )


@pytest.mark.parametrize(
    "exception",
    [
        requests.Timeout("timeout"),
        requests.ConnectionError("connection"),
        requests.RequestException("request"),
    ],
)
def test_transport_failures_have_explicit_gateway_errors(exception):
    client = gateway()
    client.session.post.side_effect = exception

    with pytest.raises(
        (
            PaymentGatewayTimeoutError,
            PaymentGatewayUnavailableError,
        )
    ):
        client._post(
            path="/payment/verify.json",
            payload={},
            operation="verify",
        )


def test_timeout_is_retryable():
    client = gateway()
    client.session.post.side_effect = requests.Timeout("timeout")

    with pytest.raises(PaymentGatewayTimeoutError) as exc_info:
        client._post(
            path="/payment/verify.json",
            payload={},
            operation="verify",
        )

    assert exc_info.value.retryable is True


@pytest.mark.parametrize("status_code", [500, 502, 503])
def test_server_errors_are_temporarily_unavailable(status_code):
    client = gateway()
    response = Mock(status_code=status_code)
    client.session.post.return_value = response

    with pytest.raises(PaymentGatewayUnavailableError) as exc_info:
        client._post(
            path="/payment/verify.json",
            payload={},
            operation="verify",
        )

    assert exc_info.value.retryable is True


@pytest.mark.parametrize("status_code", [401, 403])
def test_authentication_http_errors_are_explicit(status_code):
    client = gateway()
    response = Mock(status_code=status_code)
    client.session.post.return_value = response

    with pytest.raises(PaymentGatewayAuthenticationError):
        client._post(
            path="/payment/verify.json",
            payload={},
            operation="verify",
        )


@pytest.mark.parametrize("status_code", [400, 404, 422])
def test_other_http_errors_are_not_transport_success(status_code):
    client = gateway()
    response = Mock(status_code=status_code)
    client.session.post.return_value = response

    with pytest.raises(PaymentGatewayInvalidResponseError):
        client._post(
            path="/payment/verify.json",
            payload={},
            operation="verify",
        )


def test_invalid_json_is_an_explicit_protocol_error():
    client = gateway()
    response = Mock(status_code=200)
    response.json.side_effect = ValueError("invalid json")
    client.session.post.return_value = response

    with pytest.raises(PaymentGatewayInvalidResponseError):
        client._post(
            path="/payment/verify.json",
            payload={},
            operation="verify",
        )


@pytest.mark.parametrize("payload", [[], "invalid", 123, None])
def test_invalid_response_structure_is_explicit(payload):
    client = gateway()
    response = Mock(status_code=200)
    response.json.return_value = payload
    client.session.post.return_value = response

    with pytest.raises(PaymentGatewayInvalidResponseError):
        client._post(
            path="/payment/verify.json",
            payload={},
            operation="verify",
        )
