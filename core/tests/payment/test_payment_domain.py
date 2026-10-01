# core/tests/payment/test_payment_domain.py
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from payment.enums import (
    Currency,
    PaymentGateway,
    PaymentStatusType,
)
from tests.builders import PaymentScenarioBuilder ,OrderScenarioBuilder
from tests.factories.payment import PaymentFactory


pytestmark = pytest.mark.django_db


# ================================
# HELPERS
# ================================

def validation_message(exc: ValidationError) -> str:
    """
    Normalize Django ValidationError into a predictable string
    for assertions where the exact error structure is irrelevant.
    """
    return str(exc)

def build_valid_payment(**kwargs):
    """
    Build a Payment with a persisted, valid Order.

    This helper exists only to satisfy Payment's required
    relational dependencies during domain tests.

    It must NOT reproduce production business logic.
    """
    order = kwargs.pop("order", None)

    if order is None:
        order = OrderScenarioBuilder().with_items(1).build().order

    return PaymentFactory.build(
        order=order,
        **kwargs,
    )

# ================================
# PAYMENT STATE
# ================================

class TestPaymentStateMachine:
    """
    Payment aggregate state-machine tests.

    Authoritative lifecycle:
    
        PENDING
          ├── SUCCESS
          └── FAILED

        SUCCESS -> terminal
        FAILED  -> terminal
    """

    def test_new_payment_is_pending(self):
        payment = PaymentFactory()

        assert payment.status == PaymentStatusType.PENDING
        assert payment.is_pending
        assert not payment.is_successful
        assert not payment.is_failed
        assert not payment.is_terminal

    def test_pending_can_transition_to_success(self):
        payment = PaymentFactory()

        payment.succeed()

        assert payment.status == PaymentStatusType.SUCCESS
        assert payment.is_successful
        assert payment.is_terminal

    def test_pending_can_transition_to_failed(self):
        payment = PaymentFactory()

        payment.fail()

        assert payment.status == PaymentStatusType.FAILED
        assert payment.is_failed
        assert payment.is_terminal

    def test_success_is_terminal(self):
        payment = PaymentFactory(success=True)

        assert payment.is_terminal

    def test_failed_is_terminal(self):
        payment = PaymentFactory(failed=True)

        assert payment.is_terminal

    def test_success_cannot_transition_to_failed(self):
        payment = PaymentFactory(success=True)

        with pytest.raises(ValidationError):
            payment.fail()

    def test_failed_cannot_transition_to_success(self):
        payment = PaymentFactory(failed=True)

        with pytest.raises(ValidationError):
            payment.succeed()

    def test_success_cannot_return_to_pending(self):
        payment = PaymentFactory(success=True)

        with pytest.raises(ValidationError):
            payment._transition_to(PaymentStatusType.PENDING)

    def test_failed_cannot_return_to_pending(self):
        payment = PaymentFactory(failed=True)

        with pytest.raises(ValidationError):
            payment._transition_to(PaymentStatusType.PENDING)

    def test_success_cannot_transition_to_success_again_through_transition(self):
        payment = PaymentFactory(success=True)

        # Explicitly calling the internal transition with the same state
        # should remain harmless and deterministic.
        payment._transition_to(PaymentStatusType.SUCCESS)

        assert payment.is_successful

    def test_failed_cannot_transition_to_failed_again_through_transition(self):
        payment = PaymentFactory(failed=True)

        payment._transition_to(PaymentStatusType.FAILED)

        assert payment.is_failed

# ================================
# PAYMENT IDEMPOTENCY
# ================================

class TestPaymentIdempotency:
    """
    Domain-level idempotency.

    Important distinction:
        model idempotency
            !=
        database persistence idempotency

    These tests only prove that repeated domain commands do not
    create a second state transition.
    """

    def test_succeed_is_idempotent(self):
        payment = PaymentFactory()

        result_1 = payment.succeed()
        result_2 = payment.succeed()

        assert result_1 is payment
        assert result_2 is payment
        assert payment.is_successful

    def test_fail_is_idempotent(self):
        payment = PaymentFactory()

        result_1 = payment.fail()
        result_2 = payment.fail()

        assert result_1 is payment
        assert result_2 is payment
        assert payment.is_failed

    def test_consume_is_idempotent(self):
        payment = PaymentFactory(success=True)

        payment.consume()
        payment.consume()

        assert payment.is_consumed

    def test_refund_flag_is_idempotent(self):
        payment = PaymentFactory(
            success=True,
            consumed=True,
        )

        payment.refund()
        payment.refund()

        assert payment.is_refunded

# ================================
# PAYMENT CONSUMPTION
# ================================

class TestPaymentConsumption:
    """
    Consumption is separate from payment success.

        SUCCESS + unconsumed
                  ↓
               consume
                  ↓
        SUCCESS + consumed
    """

    def test_successful_payment_can_be_consumed(self):
        payment = PaymentFactory(success=True)

        assert not payment.is_consumed

        payment.consume()

        assert payment.is_consumed
        assert payment.is_successful

    def test_pending_payment_cannot_be_consumed(self):
        payment = PaymentFactory()

        with pytest.raises(ValidationError):
            payment.consume()

        assert not payment.is_consumed

    def test_failed_payment_cannot_be_consumed(self):
        payment = PaymentFactory(failed=True)

        with pytest.raises(ValidationError):
            payment.consume()

        assert not payment.is_consumed

    def test_consumed_payment_remains_consumed(self):
        payment = PaymentFactory(consumed=True)

        payment.consume()

        assert payment.is_consumed

    def test_consumed_payment_is_successful(self):
        payment = PaymentFactory(consumed=True)

        assert payment.is_successful
        assert payment.is_consumed

    def test_consumed_payment_cannot_become_unconsumed(self):
        payment = PaymentFactory(consumed=True)

        payment.is_consumed = False

        # Domain model should not expose an "unconsume" command.
        # This test intentionally checks that no public reverse
        # transition exists.
        assert not hasattr(payment, "unconsume")

# ================================
# REFUND PARTICIPATION
# ================================

class TestPaymentRefundState:
    """
    Payment.is_refunded means FULL refund only.
    Partial refund authorization is intentionally outside the model.
    """

    def test_successful_consumed_payment_can_be_refunded(self):
        payment = PaymentFactory(
            success=True,
            consumed=True,
        )

        assert payment.can_refund

    def test_pending_payment_cannot_be_refunded(self):
        payment = PaymentFactory()

        assert not payment.can_refund

    def test_failed_payment_cannot_be_refunded(self):
        payment = PaymentFactory(failed=True)

        assert not payment.can_refund

    def test_successful_unconsumed_payment_cannot_be_refunded(self):
        payment = PaymentFactory(success=True)

        assert not payment.can_refund

    def test_full_refund_requires_consumption(self):
        payment = PaymentFactory(success=True)

        with pytest.raises(ValidationError):
            payment.refund()

        assert not payment.is_refunded

    def test_refund_marks_payment_as_fully_refunded(self):
        payment = PaymentFactory(
            success=True,
            consumed=True,
        )

        payment.refund()

        assert payment.is_refunded
        assert payment.is_fully_refunded

    def test_failed_payment_cannot_be_marked_refunded(self):
        payment = PaymentFactory(
            failed=True,
        )

        with pytest.raises(ValidationError):
            payment.refund()

        assert not payment.is_refunded

    def test_refunded_payment_remains_refunded(self):
        payment = PaymentFactory(
            refunded=True,
        )

        payment.refund()

        assert payment.is_refunded

# ================================
# FINANCIAL SNAPSHOT
# ================================

class TestPaymentFinancialSnapshot:
    """
    Payment.amount and Payment.currency are historical financial
    snapshots.
    This test suite deliberately does NOT introduce a mutation API.
    """

    def test_matching_amount_and_currency_are_valid(self):
        payment = PaymentFactory(
            amount=Decimal("1000000"),
            currency=Currency.IRR,
        )

        payment.validate_financial_snapshot(
            amount=Decimal("1000000"),
            currency=Currency.IRR,
        )

    def test_different_amount_is_rejected(self):
        payment = PaymentFactory(
            amount=Decimal("1000000"),
            currency=Currency.IRR,
        )

        with pytest.raises(ValidationError):
            payment.validate_financial_snapshot(
                amount=Decimal("900000"),
                currency=Currency.IRR,
            )

    def test_different_currency_is_rejected(self):
        payment = PaymentFactory(
            amount=Decimal("1000000"),
            currency=Currency.IRR,
        )

        with pytest.raises(ValidationError):
            payment.validate_financial_snapshot(
                amount=Decimal("1000000"),
                currency="USD",
            )

    def test_amount_is_positive(self):
        payment = build_valid_payment(
            amount=Decimal("1000000"),
        )

        payment.full_clean()

    def test_zero_amount_is_invalid(self):
        payment = PaymentFactory.build(
            amount=Decimal("0"),
        )

        with pytest.raises(ValidationError):
            payment.full_clean()

    def test_negative_amount_is_invalid(self):
        payment = PaymentFactory.build(
            amount=Decimal("-1"),
        )

        with pytest.raises(ValidationError):
            payment.full_clean()

    def test_empty_currency_is_invalid(self):
        payment = PaymentFactory.build(
            currency="",
        )

        with pytest.raises(ValidationError):
            payment.full_clean()

# ================================
# DATABASE CONSTRAINTS
# ================================

class TestPaymentDatabaseConstraints:
    """
    Python validation is not enough.

    PostgreSQL constraints are part of the financial integrity
    boundary.
    """

    def test_database_rejects_zero_amount(self):
        payment = build_valid_payment(
            amount=Decimal("0"),
        )

        with pytest.raises(IntegrityError):
            payment.save(force_insert=True)

    def test_database_rejects_negative_amount(self):
        payment = build_valid_payment(
            amount=Decimal("-1"),
        )

        with pytest.raises(IntegrityError):
            payment.save(force_insert=True)

    def test_database_rejects_invalid_version(self):
        payment = build_valid_payment(
            version=0,
        )

        with pytest.raises(IntegrityError):
            payment.save(force_insert=True)

    def test_database_allows_only_one_pending_payment_per_order(self):
        payment = PaymentFactory()

        with pytest.raises(IntegrityError):
            PaymentFactory(order=payment.order)

    def test_successful_payment_does_not_conflict_with_pending_constraint(self):
        payment = PaymentFactory()

        payment.succeed()
        payment.save(update_fields=["status"])

        second = PaymentFactory(order=payment.order)

        assert second.is_pending

# ================================
# MODEL CLEAN INVARIANTS
# ================================

class TestPaymentCleanInvariants:
    def test_consumed_requires_success(self):
        payment = PaymentFactory.build(
            status=PaymentStatusType.PENDING,
            is_consumed=True,
        )

        with pytest.raises(ValidationError):
            payment.full_clean()

    def test_refunded_requires_success(self):
        payment = PaymentFactory.build(
            status=PaymentStatusType.PENDING,
            is_refunded=True,
        )

        with pytest.raises(ValidationError):
            payment.full_clean()

    def test_refunded_requires_consumed(self):
        payment = PaymentFactory.build(
            status=PaymentStatusType.SUCCESS,
            is_consumed=False,
            is_refunded=True,
        )

        with pytest.raises(ValidationError):
            payment.full_clean()

    def test_valid_refunded_state_passes_clean(self):
        payment = build_valid_payment(
            status=PaymentStatusType.SUCCESS,
            is_consumed=True,
            is_refunded=True,
        )

        payment.full_clean()

# ================================
# REQUIRE HELPERS
# ================================

class TestPaymentRequirements:
    def test_require_pending_passes_for_pending(self):
        payment = PaymentFactory()

        payment.require_pending()

    def test_require_pending_rejects_success(self):
        payment = PaymentFactory(success=True)

        with pytest.raises(ValidationError):
            payment.require_pending()

    def test_require_successful_passes_for_success(self):
        payment = PaymentFactory(success=True)

        payment.require_successful()

    def test_require_successful_rejects_pending(self):
        payment = PaymentFactory()

        with pytest.raises(ValidationError):
            payment.require_successful()

    def test_require_failed_passes_for_failed(self):
        payment = PaymentFactory(failed=True)

        payment.require_failed()

    def test_require_consumed_rejects_unconsumed(self):
        payment = PaymentFactory(success=True)

        with pytest.raises(ValidationError):
            payment.require_consumed()

    def test_require_not_consumed_rejects_consumed(self):
        payment = PaymentFactory(consumed=True)

        with pytest.raises(ValidationError):
            payment.require_not_consumed()

    def test_require_terminal_passes_for_success(self):
        payment = PaymentFactory(success=True)

        payment.require_terminal()

    def test_require_terminal_passes_for_failed(self):
        payment = PaymentFactory(failed=True)

        payment.require_terminal()

    def test_require_terminal_rejects_pending(self):
        payment = PaymentFactory()

        with pytest.raises(ValidationError):
            payment.require_terminal()

    def test_require_not_terminal_passes_for_pending(self):
        payment = PaymentFactory()

        payment.require_not_terminal()

    def test_require_not_terminal_rejects_success(self):
        payment = PaymentFactory(success=True)

        with pytest.raises(ValidationError):
            payment.require_not_terminal()

# ================================
# PROPERTY CONSISTENCY
# ================================

class TestPaymentPropertyConsistency:
    @pytest.mark.parametrize(
        "trait,expected",
        [
            (
                "pending",
                {
                    "pending": True,
                    "success": False,
                    "failed": False,
                    "terminal": False,
                },
            ),
            (
                "success",
                {
                    "pending": False,
                    "success": True,
                    "failed": False,
                    "terminal": True,
                },
            ),
            (
                "failed",
                {
                    "pending": False,
                    "success": False,
                    "failed": True,
                    "terminal": True,
                },
            ),
        ],
    )
    def test_state_properties_are_consistent(self, trait, expected):
        kwargs = {}

        if trait == "success":
            kwargs["success"] = True
        elif trait == "failed":
            kwargs["failed"] = True

        payment = PaymentFactory(**kwargs)

        assert payment.is_pending is expected["pending"]
        assert payment.is_successful is expected["success"]
        assert payment.is_failed is expected["failed"]
        assert payment.is_terminal is expected["terminal"]

# ================================
# FINANCIAL IMMUTABILITY API
# ================================

class TestPaymentFinancialImmutabilityContract:
    """
    This suite documents an architectural rule:

    There must be no domain command such as:
        change_amount()
        change_currency()
        change_order()

    after creation.

    The actual persistence layer will later enforce this through
    repository/CAS rules and potentially database-level protection.
    """

    def test_payment_has_no_amount_mutation_command(self):
        payment = PaymentFactory()

        assert not hasattr(payment, "change_amount")
        assert not hasattr(payment, "set_amount")
        assert not hasattr(payment, "update_amount")

    def test_payment_has_no_currency_mutation_command(self):
        payment = PaymentFactory()

        assert not hasattr(payment, "change_currency")
        assert not hasattr(payment, "set_currency")
        assert not hasattr(payment, "update_currency")

    def test_payment_has_no_order_mutation_command(self):
        payment = PaymentFactory()

        assert not hasattr(payment, "change_order")
        assert not hasattr(payment, "set_order")
        assert not hasattr(payment, "update_order")

# ================================
# UNKNOWN / INVALID STATE DEFENSE
# ================================

class TestPaymentInvalidStateDefense:
    def test_invalid_status_is_rejected_by_full_clean(self):
        payment = PaymentFactory.build(
            status=999,
        )

        with pytest.raises(ValidationError):
            payment.full_clean()