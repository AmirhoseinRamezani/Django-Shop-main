# # tests/services/payment/test_verify_payment.py

import pytest

from django.core.exceptions import ValidationError

from tests.base import BaseTestCase

from payment.services.verify import verify_payment

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]

class TestVerifyPayment(BaseTestCase):

    def test_success_verify(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        verify_payment(
            authority=payment.authority_id,
            ref_id=999999,
            response={"status": "ok"},
        )

        self.assert_payment_success(payment)

        self.assert_order_paid(payment.order)

    def test_verify_twice_is_idempotent(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        verify_payment(
            authority=payment.authority_id,
            ref_id=111,
        )

        verify_payment(
            authority=payment.authority_id,
            ref_id=111,
        )

        payment.refresh_from_db()

        assert payment.status == payment.status

    def test_failed_payment_cannot_verify(
        self,
        payment_factory,
    ):
        payment = payment_factory(
            failed=True,
        )

        with pytest.raises(
            ValidationError
        ):
            verify_payment(
                authority=payment.authority_id,
                ref_id=1,
            )

    def test_payment_consumed(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        verify_payment(
            authority=payment.authority_id,
            ref_id=555,
        )

        payment.refresh_from_db()

        assert payment.is_consumed

    def test_order_status_changed(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        verify_payment(
            authority=payment.authority_id,
            ref_id=777,
        )

        payment.order.refresh_from_db()

        assert payment.order.is_paid

    def test_ref_id_saved(
        self,
        payment_factory,
    ):
        payment = payment_factory()

        verify_payment(
            authority=payment.authority_id,
            ref_id=123456,
        )

        payment.refresh_from_db()

        assert payment.ref_id == 123456