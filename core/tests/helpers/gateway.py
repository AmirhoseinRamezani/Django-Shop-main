# tests/helpers/gateway.py
from unittest.mock import Mock


def fake_gateway(
    mocker,
    *,
    authority="AUTH-123456",
    url="https://gateway.test",
):
    gateway = mocker.patch(
        "payment.services.services.ZarinPalSandbox"
    )

    gateway.return_value.payment_request.return_value = {
        "Authority": authority,
    }

    gateway.return_value.generate_payment_url.return_value = url

    return gateway