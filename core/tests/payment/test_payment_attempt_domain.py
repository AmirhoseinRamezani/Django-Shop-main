# core\tests\payment\test_payment_attempt_domain.py
"""
Domain tests for PaymentAttempt.

These tests verify:

    - lifecycle states
    - valid transitions
    - terminal-state protection
    - idempotent terminal operations
    - gateway identity invariants
    - gateway metadata preservation
    - retry-chain invariants
    - timing invariants
    - latency invariants
    - PostgreSQL structural constraints

These tests intentionally do not test:

    - gateway adapters
    - repositories
    - application services
    - HTTP calls
    - transactions/locking
    - Payment aggregate business rules
    - Refund behavior
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from payment.enums import PaymentAttemptStatus
from payment.models import PaymentAttempt

from tests.factories.payment import PaymentAttemptFactory, PaymentFactory


pytestmark = pytest.mark.django_db


TERMINAL_STATUSES = (
    PaymentAttemptStatus.SUCCESS,
    PaymentAttemptStatus.FAILED,
    PaymentAttemptStatus.TIMEOUT,
    PaymentAttemptStatus.CANCELLED,
)


def build_pending_attempt(**kwargs) -> PaymentAttempt:
    """Create and persist a valid pending attempt."""
    return PaymentAttemptFactory.create(**kwargs)


def build_successful_attempt(**kwargs) -> PaymentAttempt:
    """Create and persist a valid successful attempt."""
    return PaymentAttemptFactory.create(
        success=True,
        **kwargs,
    )


class TestPaymentAttemptLifecycle:
    def test_default_attempt_starts_pending(self):
        attempt = build_pending_attempt()

        assert attempt.status == PaymentAttemptStatus.PENDING
        assert attempt.is_pending is True
        assert attempt.is_terminal is False
        assert attempt.is_finished is False
        assert attempt.finished_at is None

    @pytest.mark.parametrize(
        "status",
        TERMINAL_STATUSES,
    )
    def test_terminal_attempt_is_terminal(
        self,
        status: PaymentAttemptStatus,
    ):
        attempt = PaymentAttemptFactory.create(
            **{
                {
                    PaymentAttemptStatus.SUCCESS: "success",
                    PaymentAttemptStatus.FAILED: "failed",
                    PaymentAttemptStatus.TIMEOUT: "timeout",
                    PaymentAttemptStatus.CANCELLED: "cancelled",
                }[status]: True
            }
        )

        assert attempt.status == status
        assert attempt.is_terminal is True
        assert attempt.is_finished is True
        assert attempt.finished_at is not None

    def test_pending_can_transition_to_success(self):
        attempt = build_pending_attempt()

        started_at = attempt.started_at

        attempt.mark_success(
            authority_id="AUTH-TEST-001",
            gateway_reference="REF-TEST-001",
            gateway_transaction_id="TXN-TEST-001",
            response_code="100",
            gateway_message="Payment successful",
            latency_ms=120,
        )

        assert attempt.status == PaymentAttemptStatus.SUCCESS
        assert attempt.is_success is True
        assert attempt.is_terminal is True
        assert attempt.is_finished is True
        assert attempt.finished_at is not None
        assert attempt.finished_at >= started_at

    def test_pending_can_transition_to_failed(self):
        attempt = build_pending_attempt()

        attempt.mark_failed(
            reason="Gateway rejected payment",
            response_code="-1",
            gateway_message="Payment failed",
            latency_ms=250,
        )

        assert attempt.status == PaymentAttemptStatus.FAILED
        assert attempt.is_failed is True
        assert attempt.is_terminal is True
        assert attempt.is_finished is True
        assert attempt.failure_reason == "Gateway rejected payment"
        assert attempt.response_code == "-1"
        assert attempt.gateway_message == "Payment failed"

    def test_pending_can_transition_to_timeout(self):
        attempt = build_pending_attempt()

        attempt.mark_timeout(
            reason="Gateway timeout",
            latency_ms=5000,
        )

        assert attempt.status == PaymentAttemptStatus.TIMEOUT
        assert attempt.is_timeout is True
        assert attempt.is_terminal is True
        assert attempt.is_finished is True
        assert attempt.failure_reason == "Gateway timeout"

    def test_pending_can_transition_to_cancelled(self):
        attempt = build_pending_attempt()

        attempt.mark_cancelled(
            reason="User cancelled payment",
        )

        assert attempt.status == PaymentAttemptStatus.CANCELLED
        assert attempt.is_cancelled is True
        assert attempt.is_terminal is True
        assert attempt.is_finished is True
        assert attempt.failure_reason == "User cancelled payment"


class TestPaymentAttemptStateMachine:
    @pytest.mark.parametrize(
        "target",
        TERMINAL_STATUSES,
    )
    def test_pending_allows_each_terminal_transition(
        self,
        target: PaymentAttemptStatus,
    ):
        attempt = build_pending_attempt()

        if target == PaymentAttemptStatus.SUCCESS:
            attempt.mark_success(
                authority_id="AUTH-STATE-001",
                gateway_reference="REF-STATE-001",
            )
        elif target == PaymentAttemptStatus.FAILED:
            attempt.mark_failed(
                reason="failed",
            )
        elif target == PaymentAttemptStatus.TIMEOUT:
            attempt.mark_timeout(
                reason="timeout",
            )
        elif target == PaymentAttemptStatus.CANCELLED:
            attempt.mark_cancelled(
                reason="cancelled",
            )

        assert attempt.status == target
        assert attempt.is_terminal is True

    @pytest.mark.parametrize(
        "initial_status",
        TERMINAL_STATUSES,
    )
    @pytest.mark.parametrize(
        "target_status",
        TERMINAL_STATUSES,
    )
    def test_terminal_attempt_cannot_transition_to_different_terminal_state(
        self,
        initial_status: PaymentAttemptStatus,
        target_status: PaymentAttemptStatus,
    ):
        if initial_status == target_status:
            pytest.skip("Same-state transitions are explicitly idempotent.")

        kwargs = {
            {
                PaymentAttemptStatus.SUCCESS: "success",
                PaymentAttemptStatus.FAILED: "failed",
                PaymentAttemptStatus.TIMEOUT: "timeout",
                PaymentAttemptStatus.CANCELLED: "cancelled",
            }[initial_status]: True
        }

        attempt = PaymentAttemptFactory.create(**kwargs)

        with pytest.raises(ValidationError):
            if target_status == PaymentAttemptStatus.SUCCESS:
                attempt.mark_success(
                    authority_id=attempt.authority_id,
                    gateway_reference=attempt.gateway_reference,
                    gateway_transaction_id=attempt.gateway_transaction_id,
                )
            elif target_status == PaymentAttemptStatus.FAILED:
                attempt.mark_failed(reason="new failure")
            elif target_status == PaymentAttemptStatus.TIMEOUT:
                attempt.mark_timeout(reason="new timeout")
            elif target_status == PaymentAttemptStatus.CANCELLED:
                attempt.mark_cancelled(reason="new cancellation")

        assert attempt.status == initial_status

    @pytest.mark.parametrize(
        "status",
        TERMINAL_STATUSES,
    )
    def test_terminal_attempt_cannot_return_to_pending(
        self,
        status: PaymentAttemptStatus,
    ):
        kwargs = {
            {
                PaymentAttemptStatus.SUCCESS: "success",
                PaymentAttemptStatus.FAILED: "failed",
                PaymentAttemptStatus.TIMEOUT: "timeout",
                PaymentAttemptStatus.CANCELLED: "cancelled",
            }[status]: True
        }

        attempt = PaymentAttemptFactory.create(**kwargs)

        with pytest.raises(ValidationError):
            attempt._require_transition(
                PaymentAttemptStatus.PENDING,
            )

        assert attempt.status == status


class TestPaymentAttemptIdempotency:
    def test_success_is_idempotent_for_identical_identity(self):
        attempt = build_pending_attempt()

        attempt.mark_success(
            authority_id="AUTH-IDEMP-001",
            gateway_reference="REF-IDEMP-001",
            gateway_transaction_id="TXN-IDEMP-001",
            response_code="100",
            gateway_message="Payment successful",
            latency_ms=120,
        )

        finished_at = attempt.finished_at
        latency_ms = attempt.latency_ms

        result = attempt.mark_success(
            authority_id="AUTH-IDEMP-001",
            gateway_reference="REF-IDEMP-001",
            gateway_transaction_id="TXN-IDEMP-001",
            response_code="100",
            gateway_message="Payment successful",
            latency_ms=999,
        )

        assert result is attempt
        assert attempt.status == PaymentAttemptStatus.SUCCESS
        assert attempt.finished_at == finished_at
        assert attempt.latency_ms == latency_ms
        assert attempt.authority_id == "AUTH-IDEMP-001"
        assert attempt.gateway_reference == "REF-IDEMP-001"
        assert attempt.gateway_transaction_id == "TXN-IDEMP-001"

    @pytest.mark.parametrize(
        "trait,method_name,kwargs",
        [
            (
                "failed",
                "mark_failed",
                {
                    "reason": "Gateway failure",
                    "response_code": "-1",
                    "gateway_message": "Failed",
                    "latency_ms": 250,
                },
            ),
            (
                "timeout",
                "mark_timeout",
                {
                    "reason": "Gateway timeout",
                    "latency_ms": 5000,
                },
            ),
            (
                "cancelled",
                "mark_cancelled",
                {
                    "reason": "Cancelled",
                },
            ),
        ],
    )
    def test_terminal_operation_is_idempotent(
        self,
        trait: str,
        method_name: str,
        kwargs: dict[str, object],
    ):
        attempt = PaymentAttemptFactory.create(**{trait: True})

        original_status = attempt.status
        original_finished_at = attempt.finished_at
        original_latency = attempt.latency_ms

        getattr(attempt, method_name)(**kwargs)

        assert attempt.status == original_status
        assert attempt.finished_at == original_finished_at
        assert attempt.latency_ms == original_latency

    def test_repeated_success_can_add_late_transaction_id(self):
        attempt = build_pending_attempt()

        attempt.mark_success(
            authority_id="AUTH-LATE-001",
            gateway_reference="REF-LATE-001",
        )

        assert attempt.gateway_transaction_id == ""

        attempt.mark_success(
            authority_id="AUTH-LATE-001",
            gateway_reference="REF-LATE-001",
            gateway_transaction_id="TXN-LATE-001",
        )

        assert attempt.gateway_transaction_id == "TXN-LATE-001"


class TestPaymentAttemptGatewayIdentity:
    def test_success_requires_authority(self):
        attempt = build_pending_attempt()

        with pytest.raises(ValidationError):
            attempt.mark_success(
                authority_id="",
                gateway_reference="REF-IDENTITY-001",
            )

        assert attempt.status == PaymentAttemptStatus.PENDING

    def test_success_requires_gateway_reference(self):
        attempt = build_pending_attempt()

        with pytest.raises(ValidationError):
            attempt.mark_success(
                authority_id="AUTH-IDENTITY-001",
                gateway_reference="",
            )

        assert attempt.status == PaymentAttemptStatus.PENDING

    def test_success_stores_gateway_identity(self):
        attempt = build_pending_attempt()

        attempt.mark_success(
            authority_id="AUTH-IDENTITY-001",
            gateway_reference="REF-IDENTITY-001",
            gateway_transaction_id="TXN-IDENTITY-001",
        )

        assert attempt.authority_id == "AUTH-IDENTITY-001"
        assert attempt.gateway_reference == "REF-IDENTITY-001"
        assert attempt.gateway_transaction_id == "TXN-IDENTITY-001"

    def test_external_reference_prefers_transaction_id(self):
        attempt = build_successful_attempt(
            gateway_transaction_id="TXN-EXTERNAL-001",
        )

        assert attempt.external_reference == "TXN-EXTERNAL-001"

    def test_external_reference_falls_back_to_gateway_reference(self):
        attempt = build_successful_attempt(
            gateway_transaction_id="",
            gateway_reference="REF-EXTERNAL-001",
        )

        assert attempt.external_reference == "REF-EXTERNAL-001"

    def test_external_reference_falls_back_to_authority(self):
        attempt = build_successful_attempt(
            gateway_transaction_id="",
            gateway_reference="REF-EXTERNAL-001",
        )

        attempt.gateway_reference = ""

        assert attempt.external_reference == "AUTH-00000000" or (
            attempt.external_reference == attempt.authority_id
        )

    def test_authority_is_immutable(self):
        attempt = build_successful_attempt(
            authority_id="AUTH-IMMUTABLE-001",
            gateway_reference="REF-IMMUTABLE-001",
        )

        with pytest.raises(ValidationError):
            attempt.mark_success(
                authority_id="AUTH-IMMUTABLE-002",
                gateway_reference="REF-IMMUTABLE-001",
            )

        assert attempt.authority_id == "AUTH-IMMUTABLE-001"

    def test_gateway_reference_is_immutable(self):
        attempt = build_successful_attempt(
            authority_id="AUTH-IMMUTABLE-003",
            gateway_reference="REF-IMMUTABLE-003",
        )

        with pytest.raises(ValidationError):
            attempt.mark_success(
                authority_id="AUTH-IMMUTABLE-003",
                gateway_reference="REF-IMMUTABLE-004",
            )

        assert attempt.gateway_reference == "REF-IMMUTABLE-003"

    def test_gateway_transaction_id_is_immutable(self):
        attempt = build_successful_attempt(
            authority_id="AUTH-IMMUTABLE-005",
            gateway_reference="REF-IMMUTABLE-005",
            gateway_transaction_id="TXN-IMMUTABLE-005",
        )

        with pytest.raises(ValidationError):
            attempt.mark_success(
                authority_id="AUTH-IMMUTABLE-005",
                gateway_reference="REF-IMMUTABLE-005",
                gateway_transaction_id="TXN-IMMUTABLE-006",
            )

        assert attempt.gateway_transaction_id == "TXN-IMMUTABLE-005"

    def test_successful_attempt_cannot_have_failure_reason(self):
        attempt = build_successful_attempt(
            failure_reason="invalid failure",
        )

        with pytest.raises(ValidationError):
            attempt.full_clean()

    def test_non_success_attempt_cannot_have_gateway_reference(self):
        attempt = build_pending_attempt(
            gateway_reference="REF-INVALID-001",
        )

        with pytest.raises(ValidationError):
            attempt.full_clean()

    def test_non_success_attempt_cannot_have_transaction_id(self):
        attempt = build_pending_attempt(
            gateway_transaction_id="TXN-INVALID-001",
        )

        with pytest.raises(ValidationError):
            attempt.full_clean()


class TestPaymentAttemptIdentityConflict:
    def test_conflicting_authority_is_rejected_on_duplicate_success(self):
        attempt = build_successful_attempt(
            authority_id="AUTH-CONFLICT-001",
            gateway_reference="REF-CONFLICT-001",
        )

        with pytest.raises(ValidationError):
            attempt.mark_success(
                authority_id="AUTH-CONFLICT-002",
                gateway_reference="REF-CONFLICT-001",
            )

        assert attempt.authority_id == "AUTH-CONFLICT-001"

    def test_conflicting_reference_is_rejected_on_duplicate_success(self):
        attempt = build_successful_attempt(
            authority_id="AUTH-CONFLICT-003",
            gateway_reference="REF-CONFLICT-003",
        )

        with pytest.raises(ValidationError):
            attempt.mark_success(
                authority_id="AUTH-CONFLICT-003",
                gateway_reference="REF-CONFLICT-004",
            )

        assert attempt.gateway_reference == "REF-CONFLICT-003"

    def test_conflicting_transaction_id_is_rejected_on_duplicate_success(self):
        attempt = build_successful_attempt(
            authority_id="AUTH-CONFLICT-005",
            gateway_reference="REF-CONFLICT-005",
            gateway_transaction_id="TXN-CONFLICT-005",
        )

        with pytest.raises(ValidationError):
            attempt.mark_success(
                authority_id="AUTH-CONFLICT-005",
                gateway_reference="REF-CONFLICT-005",
                gateway_transaction_id="TXN-CONFLICT-006",
            )

        assert attempt.gateway_transaction_id == "TXN-CONFLICT-005"


class TestPaymentAttemptRetry:
    def test_first_attempt_has_initial_retry_state(self):
        attempt = build_pending_attempt(
            attempt_number=1,
            retry_count=1,
            retry_of=None,
        )

        assert attempt.attempt_number == 1
        assert attempt.retry_count == 1
        assert attempt.retry_of_id is None

        attempt.full_clean()

    def test_retry_attempt_references_previous_attempt(self):
        payment = PaymentFactory.create()

        first = PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=1,
            retry_count=1,
        )

        second = PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=2,
            retry_count=2,
            retry_of=first,
        )

        assert second.retry_of_id == first.pk
        assert second.retry_of_id != second.pk
        assert second.payment_id == first.payment_id
        assert second.retry_count == 2

        second.full_clean()

    def test_retry_chain_preserves_history(self):
        payment = PaymentFactory.create()

        first = PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=1,
            retry_count=1,
        )

        second = PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=2,
            retry_count=2,
            retry_of=first,
        )

        third = PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=3,
            retry_count=3,
            retry_of=second,
        )

        assert first.retry_of_id is None
        assert second.retry_of_id == first.pk
        assert third.retry_of_id == second.pk

        assert first.attempt_number == 1
        assert second.attempt_number == 2
        assert third.attempt_number == 3

        assert first.retry_count == 1
        assert second.retry_count == 2
        assert third.retry_count == 3

        first.refresh_from_db()
        second.refresh_from_db()

        assert first.retry_of_id is None
        assert second.retry_of_id == first.pk
        assert second.attempt_number == 2

    def test_first_attempt_cannot_have_retry_count_greater_than_one(self):
        attempt = build_pending_attempt(
            attempt_number=1,
            retry_count=2,
            retry_of=None,
        )

        with pytest.raises(ValidationError):
            attempt.full_clean()

    def test_retry_attempt_requires_retry_count_at_least_two(self):
        payment = PaymentFactory.create()

        first = PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=1,
            retry_count=1,
        )

        retry = PaymentAttemptFactory.build(
            payment=payment,
            attempt_number=2,
            retry_count=1,
            retry_of=first,
        )

        with pytest.raises(ValidationError):
            retry.full_clean()

    def test_self_retry_is_rejected(self):
        attempt = build_pending_attempt(
            attempt_number=1,
            retry_count=1,
        )

        attempt.retry_of = attempt
        attempt.retry_count = 2

        with pytest.raises(ValidationError):
            attempt.full_clean()

    @pytest.mark.parametrize(
        "retry_count",
        [0, -1],
    )
    def test_invalid_retry_count_is_rejected(
        self,
        retry_count: int,
    ):
        attempt = PaymentAttemptFactory.build(
            retry_count=retry_count,
        )

        with pytest.raises(ValidationError):
            attempt.full_clean()

    @pytest.mark.parametrize(
        "attempt_number",
        [0, -1],
    )
    def test_invalid_attempt_number_is_rejected(
        self,
        attempt_number: int,
    ):
        attempt = PaymentAttemptFactory.build(
            attempt_number=attempt_number,
        )

        with pytest.raises(ValidationError):
            attempt.full_clean()
            
    
    @pytest.mark.parametrize(
        ("attempt_number", "retry_count"),
        [
            (1, 2),
            (2, 1),
            (3, 1),
            (3, 2),
            (2, 3),
        ],
    )
    def test_attempt_number_and_retry_count_must_match(
            self,
            attempt_number,
            retry_count,
        ):
            payment = PaymentFactory.create()

            retry_of = None

            if attempt_number > 1:
                retry_of = PaymentAttemptFactory.create(
                    payment=payment,
                    attempt_number=attempt_number - 1,
                    retry_count=attempt_number - 1,
                )

            attempt = PaymentAttemptFactory.build(
                payment=payment,
                attempt_number=attempt_number,
                retry_count=retry_count,
                retry_of=retry_of,
            )

            with pytest.raises(ValidationError):
                attempt.full_clean()
    
    def test_retry_must_reference_immediately_previous_attempt(self):
        payment = PaymentFactory.create()

        first = PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=1,
            retry_count=1,
        )

        second = PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=2,
            retry_count=2,
            retry_of=first,
        )

        invalid_third = PaymentAttemptFactory.build(
            payment=payment,
            attempt_number=4,
            retry_count=4,
            retry_of=second,
        )

        with pytest.raises(ValidationError):
            invalid_third.full_clean()
            
    def test_valid_retry_chain_is_accepted(self):
        payment = PaymentFactory.create()

        first = PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=1,
            retry_count=1,
        )

        second = PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=2,
            retry_count=2,
            retry_of=first,
        )

        third = PaymentAttemptFactory.build(
            payment=payment,
            attempt_number=3,
            retry_count=3,
            retry_of=second,
        )

        third.full_clean()

        assert third.payment_id == payment.id
        assert third.retry_of_id == second.id
        assert third.attempt_number == 3
        assert third.retry_count == 3


class TestPaymentAttemptTiming:
    def test_pending_attempt_is_unfinished(self):
        attempt = build_pending_attempt()

        assert attempt.finished_at is None
        assert attempt.is_finished is False

    @pytest.mark.parametrize(
        "trait",
        [
            "success",
            "failed",
            "timeout",
            "cancelled",
        ],
    )
    def test_terminal_attempt_has_finished_at(self, trait: str):
        attempt = PaymentAttemptFactory.create(**{trait: True})

        assert attempt.finished_at is not None
        assert attempt.is_finished is True
        assert attempt.finished_at >= attempt.started_at

    def test_finished_at_cannot_precede_started_at(self):
        attempt = build_pending_attempt()

        attempt.finished_at = attempt.started_at - timedelta(seconds=1)

        with pytest.raises(ValidationError):
            attempt.full_clean()

    def test_terminal_transition_sets_finished_at(self):
        attempt = build_pending_attempt()

        assert attempt.finished_at is None

        attempt.mark_failed(
            reason="failed",
        )

        assert attempt.finished_at is not None
        assert attempt.finished_at >= attempt.started_at

    def test_terminal_transition_preserves_finished_at_on_repeated_operation(self):
        attempt = build_pending_attempt()

        attempt.mark_timeout(
            reason="timeout",
            latency_ms=5000,
        )

        finished_at = attempt.finished_at

        attempt.mark_timeout(
            reason="timeout",
            latency_ms=9000,
        )

        assert attempt.finished_at == finished_at
        
    def test_retry_cannot_reference_attempt_from_another_payment(self):
            first_payment = PaymentFactory.create()
            second_payment = PaymentFactory.create()
    
            first_attempt = PaymentAttemptFactory.create(
                payment=first_payment,
                attempt_number=1,
                retry_count=1,
            )
    
            retry = PaymentAttemptFactory.build(
                payment=second_payment,
                attempt_number=2,
                retry_count=2,
                retry_of=first_attempt,
            )
    
            with pytest.raises(ValidationError):
                retry.full_clean()


class TestPaymentAttemptLatency:
    @pytest.mark.parametrize(
        "latency_ms",
        [0, 1, 120, 5000],
    )
    def test_non_negative_latency_is_accepted(
        self,
        latency_ms: int,
    ):
        attempt = build_pending_attempt()

        attempt.record_latency(
            latency_ms=latency_ms,
        )

        assert attempt.latency_ms == latency_ms

    def test_negative_latency_is_rejected_by_domain_api(self):
        attempt = build_pending_attempt()

        with pytest.raises(ValidationError):
            attempt.record_latency(
                latency_ms=-1,
            )

        assert attempt.latency_ms is None

    def test_negative_latency_is_rejected_by_model_validation(self):
        attempt = PaymentAttemptFactory.build(
            latency_ms=-1,
        )

        with pytest.raises(ValidationError):
            attempt.full_clean()

    def test_explicit_latency_is_preserved_on_terminal_transition(self):
        attempt = build_pending_attempt()

        attempt.mark_failed(
            reason="failed",
            latency_ms=321,
        )

        assert attempt.latency_ms == 321

    def test_existing_latency_is_preserved_on_repeated_terminal_operation(self):
        attempt = build_pending_attempt()

        attempt.mark_timeout(
            reason="timeout",
            latency_ms=5000,
        )

        attempt.mark_timeout(
            reason="timeout",
            latency_ms=9000,
        )

        assert attempt.latency_ms == 5000

    def test_latency_is_calculated_when_not_explicitly_supplied(self):
        attempt = build_pending_attempt()

        attempt.mark_failed(
            reason="failed",
        )

        assert attempt.finished_at is not None
        assert attempt.latency_ms is not None
        assert attempt.latency_ms >= 0


class TestPaymentAttemptGatewayMetadata:
    def test_gateway_response_can_be_registered_while_pending(self):
        attempt = build_pending_attempt()

        attempt.register_gateway_response(
            response_code="100",
            gateway_message="Gateway accepted request",
        )

        assert attempt.response_code == "100"
        assert attempt.gateway_message == "Gateway accepted request"
        assert attempt.status == PaymentAttemptStatus.PENDING

    def test_gateway_response_cannot_be_registered_after_terminal_state(self):
        attempt = build_successful_attempt()

        with pytest.raises(ValidationError):
            attempt.register_gateway_response(
                response_code="100",
                gateway_message="Duplicate response",
            )

    def test_terminal_transition_preserves_gateway_metadata(self):
        attempt = build_pending_attempt()

        attempt.register_gateway_response(
            response_code="100",
            gateway_message="Gateway accepted request",
        )

        attempt.mark_success(
            authority_id="AUTH-META-001",
            gateway_reference="REF-META-001",
        )

        assert attempt.response_code == "100"
        assert attempt.gateway_message == "Gateway accepted request"

    def test_empty_gateway_metadata_does_not_erase_existing_values(self):
        attempt = build_pending_attempt()

        attempt.register_gateway_response(
            response_code="100",
            gateway_message="Gateway accepted request",
        )

        attempt.mark_failed(
            reason="failed",
            response_code="",
            gateway_message="",
        )

        assert attempt.response_code == "100"
        assert attempt.gateway_message == "Gateway accepted request"

    def test_terminal_success_metadata_is_preserved(self):
        attempt = build_pending_attempt()

        attempt.mark_success(
            authority_id="AUTH-META-002",
            gateway_reference="REF-META-002",
            gateway_transaction_id="TXN-META-002",
            response_code="100",
            gateway_message="Payment successful",
        )

        assert attempt.status == PaymentAttemptStatus.SUCCESS
        assert attempt.authority_id == "AUTH-META-002"
        assert attempt.gateway_reference == "REF-META-002"
        assert attempt.gateway_transaction_id == "TXN-META-002"
        assert attempt.response_code == "100"
        assert attempt.gateway_message == "Payment successful"
        assert attempt.failure_reason == ""

    def test_terminal_failure_metadata_is_preserved(self):
        attempt = build_pending_attempt()

        attempt.mark_failed(
            reason="Gateway rejected payment",
            response_code="-1",
            gateway_message="Payment failed",
        )

        assert attempt.status == PaymentAttemptStatus.FAILED
        assert attempt.failure_reason == "Gateway rejected payment"
        assert attempt.response_code == "-1"
        assert attempt.gateway_message == "Payment failed"


class TestPaymentAttemptDatabaseConstraints:
    def test_attempt_number_must_be_positive_at_database_level(self):
        payment = PaymentFactory.create()

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentAttempt.objects.create(
                    payment=payment,
                    attempt_number=0,
                    retry_count=1,
                    status=PaymentAttemptStatus.PENDING,
                )

    def test_retry_count_must_be_positive_at_database_level(self):
        payment = PaymentFactory.create()

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentAttempt.objects.create(
                    payment=payment,
                    attempt_number=1,
                    retry_count=0,
                    status=PaymentAttemptStatus.PENDING,
                )

    def test_attempt_number_is_unique_per_payment(self):
        payment = PaymentFactory.create()

        PaymentAttemptFactory.create(
            payment=payment,
            attempt_number=1,
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentAttempt.objects.create(
                    payment=payment,
                    attempt_number=1,
                    retry_count=1,
                    status=PaymentAttemptStatus.PENDING,
                )

    def test_same_attempt_number_is_allowed_for_different_payments(self):
        first_payment = PaymentFactory.create()
        second_payment = PaymentFactory.create()

        first = PaymentAttemptFactory.create(
            payment=first_payment,
            attempt_number=1,
        )

        second = PaymentAttemptFactory.create(
            payment=second_payment,
            attempt_number=1,
        )

        assert first.pk != second.pk
        assert first.payment_id != second.payment_id
        assert first.attempt_number == second.attempt_number == 1

    def test_success_requires_gateway_reference_at_database_level(self):
        payment = PaymentFactory.create()

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentAttempt.objects.create(
                    payment=payment,
                    attempt_number=1,
                    retry_count=1,
                    status=PaymentAttemptStatus.SUCCESS,
                    authority_id="AUTH-DB-001",
                    gateway_reference="",
                    finished_at=timezone.now(),
                )

    def test_success_requires_authority_at_database_level(self):
        payment = PaymentFactory.create()

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentAttempt.objects.create(
                    payment=payment,
                    attempt_number=1,
                    retry_count=1,
                    status=PaymentAttemptStatus.SUCCESS,
                    authority_id="",
                    gateway_reference="REF-DB-001",
                    finished_at=timezone.now(),
                )

    def test_terminal_attempt_requires_finished_at_at_database_level(self):
        payment = PaymentFactory.create()

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentAttempt.objects.create(
                    payment=payment,
                    attempt_number=1,
                    retry_count=1,
                    status=PaymentAttemptStatus.FAILED,
                    finished_at=None,
                )

    def test_pending_attempt_cannot_have_finished_at_at_database_level(self):
        payment = PaymentFactory.create()

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentAttempt.objects.create(
                    payment=payment,
                    attempt_number=1,
                    retry_count=1,
                    status=PaymentAttemptStatus.PENDING,
                    finished_at=timezone.now(),
                )

    def test_finished_at_cannot_precede_started_at_at_database_level(self):
        payment = PaymentFactory.create()

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                attempt = PaymentAttempt.objects.create(
                    payment=payment,
                    attempt_number=1,
                    retry_count=1,
                    status=PaymentAttemptStatus.PENDING,
                )

                PaymentAttempt.objects.filter(pk=attempt.pk).update(
                    finished_at=attempt.started_at - timedelta(seconds=1),
                )
