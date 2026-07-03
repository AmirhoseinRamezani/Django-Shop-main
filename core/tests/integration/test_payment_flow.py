# tests/integration/test_payment_flow.py
import pytest

from payment.services.services import PaymentService
from payment.services.payment_flow import (
    handle_successful_payment,
)

from tests.helpers.session import DummySession


pytestmark = pytest.mark.django_db


class TestPaymentFlow:

    def test_payment_flow(
        self,
        paid_order,
        mocker,
    ):
        gateway = mocker.patch(
            "payment.services.services.ZarinPalSandbox"
        )

        gateway.return_value.payment_request.return_value = {
            "Authority": "AUTH-1",
        }

        gateway.return_value.generate_payment_url.return_value = (
            "url"
        )

        PaymentService.start_payment(
            paid_order,
        )

        payment = paid_order.payments.first()

        order = handle_successful_payment(
            authority=payment.authority_id,
            ref_id="REF-1",
            response={},
            session=DummySession(),
        )

        payment.refresh_from_db()

        assert payment.is_consumed

        assert order.pk == paid_order.pk
