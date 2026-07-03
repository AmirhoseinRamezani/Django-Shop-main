# tests/e2e/test_payment.py
import pytest

from payment.services.services import PaymentService
from payment.services.verify import verify_payment

from tests.assertions import (
    refresh,
    assert_payment_success,
)

pytestmark = pytest.mark.django_db


class TestPaymentLifecycle:

    def test_payment_success(
        self,
        paid_order,
        mocker,
    ):
        gateway = mocker.patch(
            "payment.services.services.ZarinPalSandbox"
        )

        gateway.return_value.payment_request.return_value = {
            "Authority": "AUTH123",
        }

        gateway.return_value.generate_payment_url.return_value = "url"

        PaymentService.start_payment(
            paid_order,
        )

        payment = paid_order.payments.first()

        verify_payment(
            authority=payment.authority_id,
            ref_id="REF123",
            response={},
        )

        refresh(payment)

        assert_payment_success(payment)