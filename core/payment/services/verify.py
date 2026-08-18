# core/payment/services/verify.py

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from order.models import OrderModel
from order.services.confirm_payment import confirm_order_payment

from payment.enums import PaymentAttemptStatus, PaymentStatusType
from payment.exceptions import (
    PaymentGatewayError,
    PaymentInvariantViolation,
)
from payment.models.payment import PaymentModel
from payment.models.payment_attempt import PaymentAttempt
from payment.policies import PaymentPolicy
from payment.repositories.payment_attempt_repository import (
    PaymentAttemptRepository,
)
from payment.repositories.payment_repository import PaymentRepository
from payment.services.gateway_service import GatewayService


@dataclass(frozen=True, slots=True)
class VerificationSnapshot:
    """
    Immutable snapshot captured before external gateway communication.

    The snapshot prevents the gateway request phase from depending on a
    mutable ORM instance after the database transaction has committed.

    Only financial / gateway identity required for verification is copied.
    """

    payment_id: int
    order_id: int

    amount: Decimal
    currency: str

    gateway: Any

    attempt_id: int
    attempt_number: int

    authority_id: str
    gateway_reference: str
    gateway_transaction_id: str


def verify_payment(
    *,
    payment_id: int,
    ref_id: str | None = None,
    response: dict[str, Any] | None = None,
) -> PaymentModel:
    """
    Verify one Payment through its authoritative PaymentAttempt.

    HARDENED VERIFICATION CONTRACT
    ===============================

    Database work and external gateway communication are deliberately
    separated.

    Phase A:
        transaction.atomic()
            -> lock Payment
            -> validate Payment
            -> resolve authoritative attempt
            -> create immutable verification snapshot
            -> commit

    Gateway phase:
        -> execute GatewayService.verify()
        -> NO database transaction
        -> NO row lock

    Phase B:
        transaction.atomic()
            -> lock Order
            -> lock Payment
            -> re-check Payment state
            -> validate gateway evidence
            -> Payment PENDING -> SUCCESS
            -> commit

    Order synchronization:
        transaction.atomic()
            -> lock Order
            -> lock Payment
            -> consume Payment
            -> synchronize Order
            -> commit

    IMPORTANT
    =========

    Payment.gateway is authoritative for gateway selection.

    PaymentAttempt is authoritative for gateway execution identity:
        authority_id
        gateway_reference
        gateway_transaction_id

    Payment.amount / currency / order are historical financial snapshots.
    Gateway callback/request data is never treated as the financial source
    of truth.
    The gateway result is evidence which must be reconciled against the
    local Payment + PaymentAttempt snapshot.

    Lock hierarchy:
        Order
            ->
        Payment
            ->
        PaymentAttempt

    No gateway HTTP request is performed while holding a database lock.
    """

    # ----------------------------------------
    # Raw callback/request context
    # ----------------------------------------
    #
    # This parameter is intentionally accepted for API compatibility.
    # Raw gateway payloads must never become financial truth.
    #
    del response

    normalized_ref_id = _normalize_optional(ref_id)

    # ================================
    # PHASE A — SNAPSHOT
    # ================================

    snapshot = _build_verification_snapshot(
        payment_id=payment_id,
    )

    # ================================
    # GATEWAY HTTP
    # ================================
    #
    # IMPORTANT:
    #
    # No transaction.atomic()
    # No select_for_update()
    #
    # The gateway call is external I/O and must never hold the Payment
    # lock.
    # ================================

    try:
        result = GatewayService.verify(
            payment=snapshot,
        )

    except PaymentGatewayError:
        """
        Unknown/transport gateway outcomes leave the Payment unchanged.

        A retry/reconciliation workflow may safely execute verification
        again later.
        """
        raise

    # ================================
    # PHASE B — RECONCILE GATEWAY RESULT
    # ================================

    with transaction.atomic():
        payment = _lock_payment_for_reconciliation(
            payment_id=payment_id,
        )

        # ------------------------------------
        # Another concurrent verifier may already have finalized it.
        # ------------------------------------

        if payment.is_successful:
            _validate_duplicate_success_identity(
                payment_id=payment.pk,
                result=result,
                snapshot=snapshot,
            )

            return payment

        if payment.is_failed:
            raise PaymentInvariantViolation(
                "A failed Payment cannot be resurrected by verification."
            )

        if not payment.is_pending:
            raise PaymentInvariantViolation(
                "Only pending Payments can be verified."
            )

        # ------------------------------------
        # Validate gateway result.
        # ------------------------------------

        _validate_gateway_result(
            result=result,
            snapshot=snapshot,
            callback_ref=normalized_ref_id,
        )

        # ------------------------------------
        # Definitive provider failure.
        # ------------------------------------

        if not result.success:
            raise PaymentGatewayError(
                result.message
                or "Payment gateway verification failed.",
                details={
                    "gateway": str(result.gateway),
                    "operation": "verify",
                    "payment_id": payment.pk,
                    "attempt_id": snapshot.attempt_id,
                    "response_code": (
                        result.response_code
                        or ""
                    ),
                },
                retryable=False,
            )

        # ------------------------------------
        # Financial snapshot validation.
        # ------------------------------------

        _validate_financial_snapshot(
            payment=payment,
            result=result,
        )

        # ------------------------------------
        # Payment state transition.
        # ------------------------------------

        payment.succeed()

        PaymentRepository.save(
            payment,
            update_fields=(
                "status",
            ),
        )

    # ================================
    # PHASE C — ORDER SYNCHRONIZATION
    # ================================
    #
    # This happens AFTER the Payment state transaction commits.
    #
    # The synchronization workflow owns its own canonical lock order:
    #
    #     Order -> Payment
    #
    # Therefore we never do:
    #
    #     Payment -> Order
    #
    # inside the same transaction.
    # ================================

    _consume_successful_payment(
        payment_id=payment_id,
    )

    return PaymentRepository.get(
        payment_id,
    )


# ================================
# PHASE A
# ================================


def _build_verification_snapshot(
    *,
    payment_id: int,
) -> VerificationSnapshot:
    """
    Build an immutable verification snapshot.

    Transaction ownership exists only for the short read/lock phase.

    The authoritative PaymentAttempt is resolved while the Payment
    aggregate is locked.
    """

    with transaction.atomic():
        payment = PaymentRepository.get_for_update(
            payment_id,
        )

        # ------------------------------------
        # Terminal success
        # ------------------------------------

        if payment.is_successful:
            """
            A successful Payment is already a terminal financial fact.

            We still return a snapshot only when necessary for callers
            that invoke verification directly.

            The main verify flow should normally avoid gateway I/O for
            already-successful Payments.
            """

            return _snapshot_from_successful_payment(
                payment=payment,
            )

        # ------------------------------------
        # Terminal failure
        # ------------------------------------

        if payment.is_failed:
            raise PaymentInvariantViolation(
                "A failed Payment cannot be verified."
            )

        # ------------------------------------
        # Domain policy
        # ------------------------------------

        PaymentPolicy.can_verify(
            payment,
        )

        if payment.state != PaymentStatusType.PENDING:
            raise PaymentInvariantViolation(
                "Only pending Payments can be verified."
            )

        # ------------------------------------
        # Resolve authoritative PaymentAttempt.
        # ------------------------------------

        attempt = _resolve_verification_attempt(
            payment_id=payment.pk,
        )

        return VerificationSnapshot(
            payment_id=payment.pk,
            order_id=payment.order_id,
            amount=payment.amount,
            currency=str(payment.currency).strip(),
            gateway=payment.gateway,
            attempt_id=attempt.pk,
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
        )


def _resolve_verification_attempt(
    *,
    payment_id: int,
) -> PaymentAttempt:
    """
    Resolve the authoritative attempt for verification.

    Only an attempt with a usable gateway authority can be verified.

    Priority:

        active PENDING attempt
            ->
        latest TIMEOUT attempt
            ->
        latest terminal attempt with authority

    The application service owns the semantic decision.

    The repository only provides persistence/query primitives.
    """

    attempt = (
        PaymentAttemptRepository
        .active_for_payment(
            payment_id,
        )
        .order_by(
            "-attempt_number",
            "-id",
        )
        .first()
    )

    if attempt is not None:
        return attempt

    attempt = (
        PaymentAttemptRepository
        .timeout_for_payment(
            payment_id,
        )
        .order_by(
            "-attempt_number",
            "-id",
        )
        .first()
    )

    if attempt is not None:
        if _normalize_optional(
            attempt.authority_id,
        ):
            return attempt

    attempt = (
        PaymentAttemptRepository
        .for_payment(
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


def _snapshot_from_successful_payment(
    *,
    payment: PaymentModel,
) -> VerificationSnapshot:
    """
    Build a snapshot for an already-successful Payment.

    This function is only a compatibility path.

    No gateway call should normally be performed for a terminal
    successful Payment.
    """

    attempt = (
        PaymentAttemptRepository
        .successful_for_payment(
            payment.pk,
        )
        .order_by(
            "-attempt_number",
            "-id",
        )
        .first()
    )

    if attempt is None:
        raise PaymentInvariantViolation(
            "Successful Payment has no successful PaymentAttempt."
        )

    return VerificationSnapshot(
        payment_id=payment.pk,
        order_id=payment.order_id,
        amount=payment.amount,
        currency=str(payment.currency).strip(),
        gateway=payment.gateway,
        attempt_id=attempt.pk,
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
    )


# ================================
# PHASE B
# ================================


def _lock_payment_for_reconciliation(
    *,
    payment_id: int,
) -> PaymentModel:
    """
    Acquire the canonical Payment aggregate lock.

    This transaction is intentionally short.

    Gateway HTTP has already completed before entering this function.
    """

    return PaymentRepository.get_for_update(
        payment_id,
    )


def _validate_gateway_result(
    *,
    result: Any,
    snapshot: VerificationSnapshot,
    callback_ref: str,
) -> None:
    """
    Validate gateway evidence before any financial mutation.

    Gateway output is evidence, not authorization.
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
        snapshot.gateway,
    )

    if result_gateway != expected_gateway:
        raise PaymentInvariantViolation(
            "Gateway verification result does not match "
            "the historical Payment gateway."
        )

    # ----------------------------------------
    # Gateway reference
    # ----------------------------------------

    gateway_reference = _normalize_optional(
        result.gateway_reference,
    )

    if not gateway_reference:
        if result.success:
            raise PaymentGatewayError(
                "Gateway verification succeeded without "
                "a gateway reference.",
                details={
                    "gateway": expected_gateway,
                    "operation": "verify",
                    "payment_id": snapshot.payment_id,
                    "attempt_id": snapshot.attempt_id,
                },
                retryable=False,
            )

        # A failed verification does not require a success identity.
        gateway_reference = ""

    # ----------------------------------------
    # Attempt authority
    # ----------------------------------------

    result_authority = _normalize_optional(
        getattr(
            result,
            "authority",
            None,
        ),
    )

    if result_authority:
        if result_authority != snapshot.authority_id:
            raise PaymentInvariantViolation(
                "Gateway verification authority does not match "
                "the PaymentAttempt authority."
            )

    # ----------------------------------------
    # Existing attempt reference
    # ----------------------------------------

    if (
        snapshot.gateway_reference
        and gateway_reference
        and gateway_reference != snapshot.gateway_reference
    ):
        raise PaymentInvariantViolation(
            "Gateway verification reference conflicts with "
            "the PaymentAttempt gateway reference."
        )

    # ----------------------------------------
    # Callback reference
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
    # Callback reference against historical attempt
    # ----------------------------------------

    if (
        callback_ref
        and snapshot.gateway_reference
        and callback_ref != snapshot.gateway_reference
    ):
        raise PaymentInvariantViolation(
            "Callback reference does not match the PaymentAttempt."
        )

    # ----------------------------------------
    # Transaction identity
    # ----------------------------------------

    result_transaction = _normalize_optional(
        result.gateway_transaction_id,
    )

    if (
        snapshot.gateway_transaction_id
        and result_transaction
        and result_transaction
        != snapshot.gateway_transaction_id
    ):
        raise PaymentInvariantViolation(
            "Gateway transaction identity conflicts with "
            "the PaymentAttempt transaction identity."
        )


def _validate_financial_snapshot(
    *,
    payment: PaymentModel,
    result: Any,
) -> None:
    """
    Verify gateway financial evidence against the immutable Payment
    snapshot.

    Never use:

        current Order.total
        current Cart
        current Product.price
        current Coupon

    as the final payment amount.
    """

    if result.amount is None:
        """
        Some gateways do not return an amount during verification.

        In that case the gateway request itself was constructed from the
        immutable Payment amount, and no contradictory gateway amount
        exists to validate.
        """
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
        normalized_result_currency = (
            str(
                result.currency,
            ).strip()
        )

        normalized_payment_currency = (
            str(
                payment.currency,
            ).strip()
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
    payment_id: int,
    result: Any,
    snapshot: VerificationSnapshot,
) -> None:
    """
    Validate a gateway result arriving after another concurrent verifier
    already finalized the Payment.

    Same financial identity:
        idempotent

    Conflicting identity:
        domain conflict
    """

    gateway_reference = _normalize_optional(
        result.gateway_reference,
    )

    gateway_transaction_id = _normalize_optional(
        result.gateway_transaction_id,
    )

    if (
        gateway_reference
        and snapshot.gateway_reference
        and gateway_reference != snapshot.gateway_reference
    ):
        raise PaymentInvariantViolation(
            "Duplicate verification returned a conflicting "
            "gateway reference."
        )

    if (
        gateway_transaction_id
        and snapshot.gateway_transaction_id
        and gateway_transaction_id
        != snapshot.gateway_transaction_id
    ):
        raise PaymentInvariantViolation(
            "Duplicate verification returned a conflicting "
            "gateway transaction ID."
        )

    if result.amount is not None:
        try:
            snapshot_amount = Decimal(
                str(
                    result.amount,
                )
            )

            if snapshot_amount != snapshot.amount:
                raise PaymentInvariantViolation(
                    "Duplicate verification returned a conflicting "
                    "financial amount."
                )

        except (TypeError, ValueError) as exc:
            raise PaymentInvariantViolation(
                "Duplicate verification returned an invalid amount."
            ) from exc

    if result.currency:
        if (
            str(
                result.currency,
            ).strip()
            != snapshot.currency
        ):
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

    Lock order is explicitly:

        Order
            ->
        Payment

    This function intentionally does not reuse the old
    Payment -> Order transaction sequence.

    The operation is idempotent.

    If Payment is already consumed, no duplicate business effect is
    produced.
    """

    with transaction.atomic():
        payment = PaymentRepository.get(
            payment_id,
        )

        order = (
            OrderModel.objects
            .select_for_update()
            .get(
                pk=payment.order_id,
            )
        )

        # ------------------------------------
        # Re-acquire Payment after Order lock.
        #
        # This establishes canonical lock order:
        #
        # Order -> Payment
        # ------------------------------------

        payment = PaymentRepository.get_for_update(
            payment_id,
        )

        if payment.is_failed:
            raise PaymentInvariantViolation(
                "A failed Payment cannot be consumed."
            )

        if not payment.is_successful:
            raise PaymentInvariantViolation(
                "Only successful Payments can be consumed."
            )

        # ------------------------------------
        # Already consumed = idempotent success.
        # ------------------------------------

        if payment.is_consumed:
            return payment

        # ------------------------------------
        # Order state validation is delegated to the order workflow.
        # ------------------------------------

        confirm_order_payment(
            order_id=order.pk,
        )

        # ------------------------------------
        # confirm_order_payment is responsible for consuming the
        # canonical successful Payment.
        #
        # Refresh the Payment state from DB after that workflow.
        # ------------------------------------

        payment.refresh_from_db()

        return payment


# ================================
# NORMALIZATION
# ================================


def _normalize_optional(
    value: Any,
) -> str:
    """
    Normalize optional textual provider identity.

    Only surrounding whitespace is removed.

    No lowercasing.
    No leading-zero removal.
    No provider-specific transformations.
    """

    return str(
        value or "",
    ).strip()


def _normalize_required(
    value: Any,
    *,
    field_name: str,
) -> str:
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
    return str(
        value.value
        if hasattr(value, "value")
        else value,
    ).strip()