# core/payment/services/verify.py

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from order.models import OrderModel
from order.services.confirm_payment import confirm_order_payment

from payment.enums import PaymentStatusType
from payment.exceptions import (
    PaymentGatewayError,
    PaymentInvariantViolation,
)
from payment.models import PaymentAttempt, PaymentModel
from payment.policies import PaymentPolicy
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from payment.repositories.payment_repository import PaymentRepository
from payment.services.gateway_service import GatewayService


# ================================
# IMMUTABLE VERIFICATION SNAPSHOTS
# ================================


@dataclass(frozen=True, slots=True)
class VerificationSnapshot:
    """
    Immutable financial/payment snapshot used during gateway verification.

    The object intentionally contains only the data required by the
    gateway boundary.

    No ORM object is used across the external gateway I/O boundary.
    """

    payment_id: int
    order_id: int

    amount: Decimal
    currency: str

    gateway: Any

    @property
    def pk(self) -> int:
        """
        Compatibility property used by GatewayService for diagnostics.
        """
        return self.payment_id


@dataclass(frozen=True, slots=True)
class AttemptVerificationSnapshot:
    """
    Immutable PaymentAttempt gateway-execution snapshot.
    PaymentAttempt owns gateway execution identity.

    In particular:
        authority_id
        gateway_reference
        gateway_transaction_id

    belong to the attempt, not the Payment aggregate.
    """

    attempt_id: int
    payment_id: int
    attempt_number: int

    authority_id: str
    gateway_reference: str
    gateway_transaction_id: str

    @property
    def pk(self) -> int:
        """
        Compatibility property used by GatewayService.
        """
        return self.attempt_id


@dataclass(frozen=True, slots=True)
class VerificationContext:
    """
    Immutable context crossing the database -> gateway boundary.
    """
    payment: VerificationSnapshot
    attempt: AttemptVerificationSnapshot

# ================================
# PUBLIC APPLICATION FLOW
# ================================

def verify_payment(
    *,
    payment_id: int,
    ref_id: str | None = None,
    response: dict[str, Any] | None = None,
) -> PaymentModel:
    """
    Verify one Payment through its authoritative PaymentAttempt.

    Transaction boundaries
    ----------------------

    Phase A
        Payment lock
            -> Attempt lock
            -> immutable snapshot
            -> COMMIT

        Phase B:
            Gateway HTTP
            -> NO DB LOCK

        Phase C:
            Payment lock
            -> Attempt lock
            -> reconcile
            -> persist
            -> COMMIT

        Phase D:
            Order lock
            -> Payment lock
            -> consume
            -> synchronize order
            -> COMMIT

    Financial rules
    ---------------

    Payment:
        owns the immutable financial snapshot.

    PaymentAttempt:
        owns gateway execution identity.

    Gateway result:
        is external evidence and must be reconciled against local state.

    Unknown gateway outcomes:
        never become confirmed failures merely because communication failed.

    External gateway I/O:
        never occurs while a database lock is held.
    """

    # ----------------------------------------
    # Raw callback payload is compatibility-only input.
    #
    # Provider-specific callback payload must never become financial
    # source of truth.
    # ----------------------------------------

    del response

    normalized_ref_id = _normalize_optional(
        ref_id,
    )

    # ========================================
    # PHASE A — IMMUTABLE SNAPSHOT
    # ========================================

    context = _build_verification_context(
        payment_id=payment_id,
    )

    # ----------------------------------------
    # Payment is already SUCCESS.
    # SUCCESS is terminal.
    # Do not call the gateway again.
    # ----------------------------------------

    if context is None:
        return _consume_successful_payment(
            payment_id=payment_id,
        )

    payment_snapshot = context.payment
    attempt_snapshot = context.attempt

    # ========================================
    # PHASE B — EXTERNAL GATEWAY COMMUNICATION
    # ========================================

    try:
        result = GatewayService.verify(
            payment=payment_snapshot,
            attempt=attempt_snapshot,
        )
    except PaymentGatewayError:
        """
        Transport/infrastructure failure.

        The financial outcome is unknown.

        Payment remains unchanged and can later be retried or
        reconciled.
        """
        raise

    # ========================================
    # PHASE C — RECONCILE GATEWAY RESULT
    # ========================================

    with transaction.atomic():
        payment = PaymentRepository.get_for_update(
            payment_id,
        )
        
        attempt = PaymentAttemptRepository.find_for_update(
            attempt_snapshot.attempt_id,
        )
        
        if attempt.payment_id != payment.pk:
            raise PaymentInvariantViolation(
                "PaymentAttempt does not belong to the expected Payment."
            )
        # ------------------------------------
        # Another verifier already finalized Payment.
        # ------------------------------------

        if payment.is_successful:
            _validate_duplicate_success_identity(
                result=result,
                payment=payment,
                payment_snapshot=payment_snapshot,
                attempt_snapshot=attempt_snapshot,
            )

            return payment

        # ------------------------------------
        # FAILED is terminal.
        # ------------------------------------

        if payment.is_failed:
            raise PaymentInvariantViolation(
                "A failed Payment cannot be resurrected by verification."
            )

        # ------------------------------------
        # Only PENDING can become SUCCESS.
        # ------------------------------------

        if not payment.is_pending:
            raise PaymentInvariantViolation(
                "Only pending Payments can be verified."
            )

        # ------------------------------------
        # External evidence must be validated before state mutation.
        # ------------------------------------

        _validate_gateway_result(
            result=result,
            payment_snapshot=payment_snapshot,
            attempt_snapshot=attempt_snapshot,
            callback_ref=normalized_ref_id,
        )

        # ------------------------------------
        # Confirmed gateway rejection.
        # This is intentionally different from transport uncertainty.
        # ------------------------------------

        if not result.success:
            raise PaymentGatewayError(
                result.message
                or "Payment gateway verification failed.",
                details={
                    "gateway": str(result.gateway),
                    "operation": "verify",
                    "payment_id": payment.pk,
                    "attempt_id": attempt.pk,
                    "response_code": (
                        result.response_code
                        or ""
                    ),
                },
                retryable=False,
            )

        # ------------------------------------
        # Validate financial evidence.
        # ------------------------------------

        _validate_financial_snapshot(
            payment=payment,
            result=result,
        )
        
        # ------------------------------------
        # Resolve gateway reference.
        #
        # Gateway verification result is authoritative.
        # Callback ref_id is compatibility fallback only.
        # ------------------------------------

        gateway_reference = _normalize_optional(
            result.gateway_reference,
        )

        if not gateway_reference:
            gateway_reference = normalized_ref_id

        if not gateway_reference:
            raise PaymentInvariantViolation(
                "Successful gateway verification requires "
                "a gateway reference."
            )
            
        gateway_transaction_id = _normalize_optional(
            result.gateway_transaction_id,
        )
        # ------------------------------------
        # Persist verified gateway evidence
        # through PaymentAttempt domain.
        # ------------------------------------

        attempt.mark_success(
            authority_id=_normalize_required(
                attempt.authority_id,
                field_name="PaymentAttempt authority",
            ),
            gateway_reference=gateway_reference,
            gateway_transaction_id=gateway_transaction_id,
            response_code=result.response_code or "",
            gateway_message=result.message or "",
        )

        PaymentAttemptRepository.save_success(
            attempt,
        )

        # ------------------------------------
        # Payment transition.
        # ------------------------------------

        payment.succeed()

        PaymentRepository.save(
            payment,
            update_fields=(
                "status",
            ),
        )

    # ========================================
    # PHASE D — ORDER / PAYMENT SYNCHRONIZATION
    # ========================================

    return _consume_successful_payment(
        payment_id=payment_id,
    )


# ================================
# PHASE A — SNAPSHOT
# ================================


def _build_verification_context(
    *,
    payment_id: int,
) -> VerificationContext | None:
    """
    Capture an immutable verification context.

    Returns:
        None
            when Payment is already SUCCESS.

        VerificationContext
            when external verification is required.

    Lock order:

        Payment
            ->
        PaymentAttempt
    """

    with transaction.atomic():
        payment = PaymentRepository.get_for_update(
            payment_id,
        )

        # ------------------------------------
        # SUCCESS is terminal and idempotent.
        # ------------------------------------

        if payment.is_successful:
            return None

        # ------------------------------------
        # FAILED is terminal.
        # ------------------------------------

        if payment.is_failed:
            raise PaymentInvariantViolation(
                "A failed Payment cannot be verified."
            )

        # ------------------------------------
        # Application-level verification policy.
        # ------------------------------------

        PaymentPolicy.can_verify(
            payment,
        )

        if payment.state != PaymentStatusType.PENDING:
            raise PaymentInvariantViolation(
                "Only pending Payments can be verified."
            )

        # ------------------------------------
        # PaymentAttempt is resolved while Payment is locked.
        # ------------------------------------

        attempt = _resolve_verification_attempt(
            payment_id=payment.pk,
        )

        return VerificationContext(
            payment=VerificationSnapshot(
                payment_id=payment.pk,
                order_id=payment.order_id,
                amount=payment.amount,
                currency=_normalize_optional(
                    payment.currency,
                ),
                gateway=payment.gateway,
            ),
            attempt=AttemptVerificationSnapshot(
                attempt_id=attempt.pk,
                payment_id=attempt.payment_id,
                attempt_number=attempt.attempt_number,
                authority_id=_normalize_required(
                    attempt.authority_id,
                    field_name="PaymentAttempt authority",
                ),
                gateway_reference=_normalize_optional(
                    attempt.gateway_reference,
                ),
                gateway_transaction_id=_normalize_optional(
                    attempt.gateway_transaction_id,
                ),
            ),
        )

def _resolve_verification_attempt(
    *,
    payment_id: int,
) -> PaymentAttempt:
    """
    Resolve the authoritative gateway execution attempt.

    Priority:
        PENDING attempt
            ->
        latest TIMEOUT attempt with authority
            ->
        latest terminal attempt with authority

    The Payment row is already locked by the caller.
    The repository only supplies persistence/query primitives.
    """

    # ----------------------------------------
    # Active/PENDING attempt
    # ----------------------------------------

    attempt = (
        PaymentAttemptRepository
        .pending_for_payment_for_update(
            payment_id,
        )
        .filter(
            authority_id__gt="",
        )
        .order_by(
            "-attempt_number",
            "-id",
        )
        .first()
    )

    if attempt is not None:
        return attempt

    # ----------------------------------------
    # Latest TIMEOUT attempt.
    #
    # A timeout does not prove gateway failure.
    # It may have produced a financial effect remotely.
    # ----------------------------------------

    attempt = (
        PaymentAttemptRepository
        .timeout_for_payment(
            payment_id,
        )
        .filter(
            authority_id__gt="",
        )
        .select_for_update()
        .order_by(
            "-attempt_number",
            "-id",
        )
        .first()
    )

    if attempt is not None:
        return attempt

    # ----------------------------------------
    # Fallback: latest terminal attempt with gateway authority.
    # ----------------------------------------

    attempt = (
        PaymentAttemptRepository
        .for_payment_for_update(
            payment_id,
        )
        .filter(
            authority_id__gt="",
        )
        .order_by(
            "-attempt_number",
            "-id",
        )
        .first()
    )

    if attempt is None:
        raise PaymentInvariantViolation(
            "Payment has no gateway attempt with an authority."
        )

    return attempt


# ================================
# GATEWAY RESULT VALIDATION
# ================================


def _validate_gateway_result(
    *,
    result: Any,
    payment_snapshot: VerificationSnapshot,
    attempt_snapshot: AttemptVerificationSnapshot,
    callback_ref: str,
) -> None:
    """
    Validate normalized GatewayService evidence.
    No financial state is changed here.
    """

    if result is None:
        raise PaymentInvariantViolation(
            "Gateway verification returned no result."
        )

    # ----------------------------------------
    # Gateway identity
    # ----------------------------------------

    result_gateway = _normalize_gateway_identity(
        result.gateway,
    )

    expected_gateway = _normalize_gateway_identity(
        payment_snapshot.gateway,
    )

    if result_gateway != expected_gateway:
        raise PaymentInvariantViolation(
            "Gateway verification result does not match "
            "the historical Payment gateway."
        )

    # ----------------------------------------
    # Successful verification must have trusted identity.
    # A success without reference is not a trustworthy financial fact.
    # ----------------------------------------

    gateway_reference = _normalize_optional(
        result.gateway_reference,
    )

    # Callback ref_id is a compatibility fallback.
    if not gateway_reference:
        gateway_reference = _normalize_optional(
            callback_ref,
        )

    if result.success and not gateway_reference:
        raise PaymentGatewayError(
            "Gateway verification succeeded without "
            "a gateway reference.",
            details={
                "gateway": expected_gateway,
                "operation": "verify",
                "payment_id": payment_snapshot.payment_id,
                "attempt_id": attempt_snapshot.attempt_id,
            },
            retryable=False,
        )

    # ----------------------------------------
    # Gateway authority must match the historical attempt.
    # ----------------------------------------

    result_authority = _normalize_optional(
        getattr(
            result,
            "authority",
            None,
        ),
    )

    if result_authority:
        if result_authority != attempt_snapshot.authority_id:
            raise PaymentInvariantViolation(
                "Gateway verification authority does not match "
                "the PaymentAttempt authority."
            )

    # ----------------------------------------
    # Existing PaymentAttempt gateway reference.
    # ----------------------------------------

    if (
        attempt_snapshot.gateway_reference
        and gateway_reference
        and gateway_reference
        != attempt_snapshot.gateway_reference
    ):
        raise PaymentInvariantViolation(
            "Gateway verification reference conflicts with "
            "the PaymentAttempt gateway reference."
        )

    # ----------------------------------------
    # Callback reference.
    # ----------------------------------------

    if (
        callback_ref
        and gateway_reference
        and callback_ref != gateway_reference
    ):
        raise PaymentInvariantViolation(
            "Callback reference does not match gateway verification."
        )

    # ----------------------------------------
    # Callback reference against historical attempt.
    # ----------------------------------------

    if (
        callback_ref
        and attempt_snapshot.gateway_reference
        and callback_ref != attempt_snapshot.gateway_reference
    ):
        raise PaymentInvariantViolation(
            "Callback reference does not match the PaymentAttempt."
        )

    # ----------------------------------------
    # Gateway transaction identity.
    # ----------------------------------------

    result_transaction = _normalize_optional(
        result.gateway_transaction_id,
    )

    if (
        attempt_snapshot.gateway_transaction_id
        and result_transaction
        and result_transaction
        != attempt_snapshot.gateway_transaction_id
    ):
        raise PaymentInvariantViolation(
            "Gateway transaction identity conflicts with "
            "the PaymentAttempt transaction identity."
        )


# ================================
# FINANCIAL EVIDENCE
# ================================


def _validate_financial_snapshot(
    *,
    payment: PaymentModel,
    result: Any,
) -> None:
    """
    Validate gateway financial evidence against immutable Payment data.

    Never derive the final amount from:
        Order
        Cart
        Product
        Coupon
    """

    if result.amount is None:
        return

    try:
        payment.validate_financial_snapshot(
            amount=result.amount,
            currency=(
                result.currency
                or payment.currency
            ),
        )
    except ValidationError as exc:
        raise PaymentInvariantViolation(
            "Gateway verification financial snapshot mismatch."
        ) from exc

    if result.currency:
        normalized_result_currency = _normalize_optional(
            result.currency,
        )

        normalized_payment_currency = _normalize_optional(
            payment.currency,
        )

        if (
            normalized_result_currency
            != normalized_payment_currency
        ):
            raise PaymentInvariantViolation(
                "Gateway verification currency does not match "
                "the Payment currency."
            )


# ================================
# DUPLICATE SUCCESS
# ================================

def _validate_duplicate_success_identity(
    *,
    result: Any,
    payment: PaymentModel,
    payment_snapshot: VerificationSnapshot,
    attempt_snapshot: AttemptVerificationSnapshot,
) -> None:
    """
    Validate a gateway result arriving after another verifier already
    finalized the Payment.

    Same identity:
        idempotent success.

    Conflicting identity:
        reject.

    The persisted Payment remains authoritative.
    """

    if not result.success:
        raise PaymentInvariantViolation(
            "A duplicate verification cannot downgrade "
            "an already successful Payment."
        )

    # ----------------------------------------
    # Gateway identity.
    # ----------------------------------------

    result_gateway = _normalize_gateway_identity(
        result.gateway,
    )

    expected_gateway = _normalize_gateway_identity(
        payment_snapshot.gateway,
    )

    if result_gateway != expected_gateway:
        raise PaymentInvariantViolation(
            "Duplicate verification returned a conflicting gateway."
        )

    # ----------------------------------------
    # Gateway reference.
    # ----------------------------------------

    gateway_reference = _normalize_optional(
        result.gateway_reference,
    )

    if (
        gateway_reference
        and attempt_snapshot.gateway_reference
        and gateway_reference
        != attempt_snapshot.gateway_reference
    ):
        raise PaymentInvariantViolation(
            "Duplicate verification returned a conflicting "
            "gateway reference."
        )

    # ----------------------------------------
    # Successful result must still have identity.
    # ----------------------------------------

    if not gateway_reference:
        raise PaymentInvariantViolation(
            "Duplicate successful verification returned no "
            "gateway reference."
        )

    # ----------------------------------------
    # Transaction identity.
    # ----------------------------------------

    gateway_transaction_id = _normalize_optional(
        result.gateway_transaction_id,
    )

    if (
        gateway_transaction_id
        and attempt_snapshot.gateway_transaction_id
        and gateway_transaction_id
        != attempt_snapshot.gateway_transaction_id
    ):
        raise PaymentInvariantViolation(
            "Duplicate verification returned a conflicting "
            "gateway transaction ID."
        )

    # ----------------------------------------
    # Financial amount.
    # ----------------------------------------

    if result.amount is not None:
        try:
            result_amount = Decimal(
                str(
                    result.amount,
                ),
            )
        except (
            TypeError,
            ValueError,
            ArithmeticError,
        ) as exc:
            raise PaymentInvariantViolation(
                "Duplicate verification returned an invalid amount."
            ) from exc

        if result_amount != payment.amount:
            raise PaymentInvariantViolation(
                "Duplicate verification returned a conflicting "
                "financial amount."
            )

    # ----------------------------------------
    # Currency.
    # ----------------------------------------

    if result.currency:
        normalized_currency = _normalize_optional(
            result.currency,
        )

        normalized_payment_currency = _normalize_optional(
            payment.currency,
        )

        if normalized_currency != normalized_payment_currency:
            raise PaymentInvariantViolation(
                "Duplicate verification returned a conflicting currency."
            )

# ================================
# ORDER / PAYMENT SYNCHRONIZATION
# ================================

def _consume_successful_payment(
    *,
    payment_id: int,
) -> PaymentModel:
    """
    Synchronize a successful Payment with its Order.

    Canonical cross-aggregate lock order:
        Order
            ->
        Payment

    The operation is idempotent.
    If Payment is already consumed, no business effect is repeated.
    """

    with transaction.atomic():
        # ------------------------------------
        # Read Payment only to discover its Order.
        # No Payment lock is held yet.
        # ------------------------------------

        payment = PaymentRepository.get(
            payment_id,
        )

        # ------------------------------------
        # Canonical cross-aggregate lock.
        # ------------------------------------

        order = (
            OrderModel.objects
            .select_for_update()
            .get(
                pk=payment.order_id,
            )
        )

        # ------------------------------------
        # Acquire Payment after Order.
        # ------------------------------------

        payment = PaymentRepository.get_for_update(
            payment_id,
        )

        # ------------------------------------
        # Defensive relationship consistency check.
        # ------------------------------------

        if payment.order_id != order.pk:
            raise PaymentInvariantViolation(
                "Payment order identity changed during synchronization."
            )

        # ------------------------------------
        # Payment state validation.
        # ------------------------------------

        if payment.is_failed:
            raise PaymentInvariantViolation(
                "A failed Payment cannot be consumed."
            )

        if not payment.is_successful:
            raise PaymentInvariantViolation(
                "Only successful Payments can be consumed."
            )

        # ------------------------------------
        # Idempotent terminal consumption.
        # ------------------------------------

        if payment.is_consumed:
            return payment

        # ------------------------------------
        # Order application workflow owns order-side effects.
        #
        # It must itself remain idempotent.
        # ------------------------------------

        confirm_order_payment(
            order_id=order.pk,
        )

        # ------------------------------------
        # Reload canonical Payment state.
        # ------------------------------------

        payment.refresh_from_db()

        if not payment.is_successful:
            raise PaymentInvariantViolation(
                "Payment lost SUCCESS state during order synchronization."
            )

        if not payment.is_consumed:
            raise PaymentInvariantViolation(
                "Successful Payment was not consumed by "
                "the order synchronization workflow."
            )

        return payment

# ================================
# NORMALIZATION
# ================================

def _normalize_optional(
    value: Any,
) -> str:
    """
    Normalize optional textual gateway identity.
    Only surrounding whitespace is removed.
    Provider-specific transformations are deliberately forbidden.
    """
    return str(
        value or "",
    ).strip()

def _normalize_required(
    value: Any,
    *,
    field_name: str,
) -> str:
    """
    Normalize and require a textual gateway identity.
    """

    normalized = _normalize_optional(
        value,
    )

    if not normalized:
        raise PaymentInvariantViolation(
            f"{field_name} is required."
        )

    return normalized

def _normalize_gateway_identity(
    value: Any,
) -> str:
    """
    Normalize PaymentGateway enum/string identity.
    No provider-specific transformation is performed.
    """

    return str(
        value.value
        if hasattr(
            value,
            "value",
        )
        else value,
    ).strip()