# tests/flows/test_payment_retry_flow.py
import pytest

from django.core.exceptions import ValidationError

from payment.services.payment import create_payment

from payment.models import PaymentStatusType

from order.models import OrderStatusType

pytestmark = pytest.mark.django_db

        
class TestRetryPayment:

    def test_retry_after_failed_payment(
        self,
        failed_order,
    ):

        payment = create_payment(
            order=failed_order,
        )

        assert payment.status == PaymentStatusType.pending

    def test_new_payment_created(
        self,
        failed_order,
    ):

        before = failed_order.payments.count()

        create_payment(
            order=failed_order,
        )

        assert failed_order.payments.count() == before + 1

    def test_order_back_to_pending(
        self,
        failed_order,
    ):

        create_payment(
            order=failed_order,
        )

        failed_order.refresh_from_db()

        assert failed_order.status == OrderStatusType.pending

    def test_return_payment(
        self,
        failed_order,
    ):

        payment = create_payment(
            order=failed_order,
        )

        assert payment.pk is not None
        
class TestRetry:

    def test_retry_only_after_failed(
        self,
        failed_order,
    ):

        payment = create_payment(
            order=failed_order,
        )

        assert payment.status == PaymentStatusType.pending

    def test_multiple_failed_payments_allowed(
        self,
        failed_order,
    ):

        create_payment(order=failed_order)

        failed_order.payments.last().status = PaymentStatusType.failed
        failed_order.payments.last().save()

        payment = create_payment(
            order=failed_order,
        )

        assert payment.pk

    def test_only_one_pending_payment(
        self,
        pending_order,
        pending_payment,
    ):

        with pytest.raises(ValidationError):

            create_payment(
                order=pending_order,
            )
            
class TestAtomicity:

    def test_gateway_failure(
        self,
        failed_order,
        mocker,
    ):

        mocker.patch(
            "payment.services.payment.gateway_create",
            side_effect=RuntimeError(),
        )

        before = failed_order.payments.count()

        with pytest.raises(RuntimeError):

            create_payment(
                order=failed_order,
            )

        assert failed_order.payments.count() == before

    def test_database_rollback(
        self,
        failed_order,
        mocker,
    ):

        mocker.patch(
            "payment.services.payment.PaymentModel.save",
            side_effect=RuntimeError(),
        )

        with pytest.raises(RuntimeError):

            create_payment(
                order=failed_order,
            )
            
class TestIdempotency:

    def test_second_retry_fails(
        self,
        failed_order,
    ):

        create_payment(
            order=failed_order,
        )

        with pytest.raises(ValidationError):

            create_payment(
                order=failed_order,
            )

    def test_no_duplicate_pending(
        self,
        failed_order,
    ):

        payment = create_payment(
            order=failed_order,
        )

        assert (
            payment.order.payments.filter(
                status=PaymentStatusType.pending,
            ).count()
            == 1
        )
        
        
