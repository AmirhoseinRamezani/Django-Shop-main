# tests/models/test_payment.py
import pytest

from payment.models import PaymentStatusType


pytestmark = pytest.mark.django_db


class TestPaymentModel:

    def test_default_status(
        self,
        payment,
    ):

        assert payment.status == PaymentStatusType.pending

    def test_mark_success(
        self,
        payment,
    ):

        payment.mark_success(
            ref_id=123456
        )

        payment.refresh_from_db()

        assert payment.status == PaymentStatusType.success

        assert payment.ref_id == 123456

    def test_mark_failed(
        self,
        payment,
    ):

        payment.mark_failed()

        payment.refresh_from_db()

        assert payment.status == PaymentStatusType.failed

    def test_string(
        self,
        payment,
    ):

        assert str(payment)
