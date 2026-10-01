# tests/models/test_payment.py
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from payment.enums import (
    PaymentStatusType,
)
from payment.models import PaymentModel


@pytest.mark.django_db
class TestPaymentStateMachine:

    def test_pending_can_succeed(
        self,
        payment,
    ):
        assert payment.status == PaymentStatusType.PENDING

        payment.succeed()

        assert (
            payment.status
            == PaymentStatusType.SUCCESS
        )

    def test_pending_can_fail(
        self,
        payment,
    ):
        payment.fail()

        assert (
            payment.status
            == PaymentStatusType.FAILED
        )

    def test_success_is_idempotent(
        self,
        payment,
    ):
        payment.succeed()

        first_status = payment.status

        payment.succeed()

        assert (
            payment.status
            == first_status
            == PaymentStatusType.SUCCESS
        )

    def test_failed_is_idempotent(
        self,
        payment,
    ):
        payment.fail()

        first_status = payment.status

        payment.fail()

        assert (
            payment.status
            == first_status
            == PaymentStatusType.FAILED
        )

    def test_success_cannot_become_failed(
        self,
        payment,
    ):
        payment.succeed()

        with pytest.raises(
            ValidationError,
        ):
            payment.fail()

    def test_failed_cannot_become_success(
        self,
        payment,
    ):
        payment.fail()

        with pytest.raises(
            ValidationError,
        ):
            payment.succeed()

    def test_success_cannot_return_to_pending(
        self,
        payment,
    ):
        payment.succeed()

        with pytest.raises(
            ValidationError,
        ):
            payment._transition_to(
                PaymentStatusType.PENDING
            )

    def test_failed_cannot_return_to_pending(
        self,
        payment,
    ):
        payment.fail()

        with pytest.raises(
            ValidationError,
        ):
            payment._transition_to(
                PaymentStatusType.PENDING
            )


@pytest.mark.django_db
class TestPaymentFinancialInvariants:

    def test_zero_amount_is_invalid(
        self,
        payment,
    ):
        payment.amount = Decimal("0")

        with pytest.raises(
            ValidationError,
        ):
            payment.full_clean()

    def test_negative_amount_is_invalid(
        self,
        payment,
    ):
        payment.amount = Decimal("-1")

        with pytest.raises(
            ValidationError,
        ):
            payment.full_clean()

    def test_consumed_requires_success(
        self,
        payment,
    ):
        payment.is_consumed = True

        with pytest.raises(
            ValidationError,
        ):
            payment.full_clean()

    def test_refunded_requires_success(
        self,
        payment,
    ):
        payment.is_refunded = True

        with pytest.raises(
            ValidationError,
        ):
            payment.full_clean()

    def test_refunded_requires_consumed(
        self,
        payment,
    ):
        payment.succeed()

        payment.is_refunded = True

        with pytest.raises(
            ValidationError,
        ):
            payment.full_clean()

    def test_consume_is_idempotent(
        self,
        payment,
    ):
        payment.succeed()

        payment.consume()

        assert payment.is_consumed is True

        payment.consume()

        assert payment.is_consumed is True

    def test_refund_is_idempotent(
        self,
        payment,
    ):
        payment.succeed()

        payment.consume()

        payment.refund()

        assert payment.is_refunded is True

        payment.refund()

        assert payment.is_refunded is True


@pytest.mark.django_db
class TestPaymentFinancialSnapshot:

    def test_matching_amount_and_currency_is_valid(
        self,
        payment,
    ):
        payment.validate_financial_snapshot(
            amount=payment.amount,
            currency=payment.currency,
        )

    def test_amount_mismatch_is_rejected(
        self,
        payment,
    ):
        with pytest.raises(
            ValidationError,
        ):
            payment.validate_financial_snapshot(
                amount=payment.amount + Decimal("1"),
                currency=payment.currency,
            )

    def test_currency_mismatch_is_rejected(
        self,
        payment,
    ):
        with pytest.raises(
            ValidationError,
        ):
            payment.validate_financial_snapshot(
                amount=payment.amount,
                currency="INVALID",
            )