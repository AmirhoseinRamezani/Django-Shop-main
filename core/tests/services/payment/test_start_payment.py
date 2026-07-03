import pytest

from django.core.exceptions import ValidationError

from payment.models import (
    PaymentModel,
    PaymentStatusType,
)

from payment.services.services import PaymentService

pytestmark = pytest.mark.django_db


class TestStartPayment:

    def test_create_payment(
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

        gateway.return_value.generate_payment_url.return_value = "url"

        url = PaymentService.start_payment(
            paid_order,
        )

        payment = PaymentModel.objects.get(
            order=paid_order,
        )

        assert payment.status == PaymentStatusType.pending
        assert payment.authority_id == "AUTH-1"
        assert url == "url"

        gateway.return_value.payment_request.assert_called_once()

    def test_duplicate_pending_payment(
        self,
        paid_order,
        payment,
    ):
        with pytest.raises(ValidationError):
            PaymentService.start_payment(
                paid_order,
            )