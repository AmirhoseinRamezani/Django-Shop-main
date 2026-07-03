# tests/services/payment/test_verify_payment.py
import pytest

from django.core.exceptions import ValidationError

from payment.models import PaymentStatusType
from payment.services.verify import verify_payment

from tests.assertions import refresh

pytestmark = pytest.mark.django_db


class TestVerifyPayment:

    def test_marks_pending_payment_success(
        self,
        payment,
        mocker,
    ):
        confirm = mocker.patch(
            "payment.services.verify.confirm_order_payment"
        )

        payment = verify_payment(
            authority=payment.authority_id,
            ref_id="REF-1",
            response={"ok": True},
        )

        refresh(payment)

        assert payment.status == PaymentStatusType.success
        assert payment.ref_id == "REF-1"

        confirm.assert_called_once_with(
            order_id=payment.order_id,
        )

    def test_success_is_idempotent(
        self,
        successful_payment,
        mocker,
    ):
        confirm = mocker.patch(
            "payment.services.verify.confirm_order_payment"
        )

        payment = verify_payment(
            authority=successful_payment.authority_id,
            ref_id=successful_payment.ref_id,
        )

        assert payment.pk == successful_payment.pk

        confirm.assert_not_called()

    def test_failed_payment_rejected(
        self,
        failed_payment,
    ):
        with pytest.raises(ValidationError):

            verify_payment(
                authority=failed_payment.authority_id,
                ref_id="1",
            )