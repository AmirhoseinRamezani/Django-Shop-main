# core/payment/services/verify.py
from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from order.services.confirm_payment import confirm_order_payment
from payment.enums import PaymentStatusType
from payment.exceptions import (
    PaymentGatewayError,
    PaymentInvariantViolation,
)
from payment.policies import PaymentPolicy
from payment.repositories.payment_repository import PaymentRepository
from payment.services.gateway_service import GatewayService

@transaction.atomic
def verify_payment(
    *,
    payment_id: int,
    ref_id: str | None = None,
    response: dict[str, Any] | None = None,
):
    """
    Verify one Payment through its historical gateway.

    Transaction contract
    --------------------
    The Payment row is locked for the complete verification workflow.

        transaction.atomic()
            ->
        lock Payment
            ->
        validate current state
            ->
        execute gateway verification
            ->
        validate gateway result
            ->
        transition Payment
            ->
        persist Payment
            ->
        confirm Order payment
            ->
        commit

    Gateway selection
    -----------------
    Payment.gateway is authoritative.
    The current configured default gateway is never used for an existing
    Payment.

    Idempotency
    ----------
    Successful Payments are already financially settled and therefore do
    not require another gateway verification.
    Failed Payments are terminal and must never be resurrected.
    Pending Payments are the only Payments eligible for gateway
    verification.

    Gateway outcome
    ---------------
    Definitive gateway failure:
        -> PaymentGatewayError(retryable=False)

    Unknown gateway/infrastructure outcome:
        -> PaymentGatewayError(retryable=True)

    Definitive gateway success:
        -> validate financial identity
        -> Payment.SUCCESS
        -> confirm Order payment

    Callback/reference reconciliation
    ----------------------------------
    ref_id is optional external callback context.
    When supplied, it must match the authoritative gateway reference
    returned by verification.

    response
    --------
    response is accepted as application-level callback/request context.
    It is intentionally not persisted here because raw provider payload
    persistence belongs to gateway observability infrastructure.
    """

    # ------------------------------------
    # Raw gateway callback/request payload
    # ------------------------------------
    #
    # Verification must never persist or trust arbitrary callback data
    # as the financial source of truth.
    # The authoritative financial result comes from GatewayService.verify().
    # Keep the parameter for API compatibility and future observability
    # integration.
    #
    del response

    # ------------------------------------
    # Canonical Payment lock
    # ------------------------------------

    payment = PaymentRepository.get_for_update(
        payment_id,
    )

    # ------------------------------------
    # Idempotent terminal success
    # ------------------------------------

    if payment.is_successful:
        """
        A successful Payment is already a terminal financial fact.
        Never call the gateway again.
        Order confirmation is intentionally idempotent and may still be
        invoked when the Payment is marked consumed.
        """

        if payment.is_consumed:
            confirm_order_payment(
                order_id=payment.order_id,
            )

        return payment

    # ------------------------------------
    # Terminal failure
    # ------------------------------------

    if payment.is_failed:
        raise PaymentInvariantViolation(
            "A failed Payment cannot be verified."
        )

    # ------------------------------------
    # Domain eligibility
    # ------------------------------------

    PaymentPolicy.can_verify(
        payment,
    )

    if payment.state != PaymentStatusType.PENDING:
        raise PaymentInvariantViolation(
            "Only pending Payments can be verified."
        )

    # ------------------------------------
    # Historical gateway verification
    # ------------------------------------

    try:
        result = GatewayService.verify(
            payment,
        )

    except PaymentGatewayError:
        """
        GatewayService distinguishes retryable/unknown infrastructure
        failures from deterministic provider errors.
        Either way, verification itself must not manufacture a Payment
        failure from an exception.
        The Payment remains PENDING until a definitive external result
        exists.
        """

        raise

    # ------------------------------------
    # Gateway result success/failure
    # ------------------------------------

    if not result.success:
        """
        The gateway explicitly returned a negative verification result.

        This is a definitive provider-level failure, not an unknown
        transport outcome.

        The Payment remains unchanged/PENDING because verification failure
        does not itself prove that the Payment should transition to the
        application's terminal FAILED state unless the domain policy
        explicitly defines that transition elsewhere.
        """

        raise PaymentGatewayError(
            result.message
            or "Payment gateway verification failed.",
            details={
                "gateway": result.gateway.value,
                "operation": "verify",
                "payment_id": payment.pk,
                "response_code": (
                    result.response_code
                    or ""
                ),
            },
            retryable=False,
        )

    # ------------------------------------
    # Gateway financial identity
    # ------------------------------------

    gateway_reference = _normalize_optional(
        result.gateway_reference,
    )

    gateway_transaction_id = _normalize_optional(
        result.gateway_transaction_id,
    )

    if not gateway_reference:
        """
        A successful verification without a gateway reference cannot be
        safely persisted as a terminal financial fact.
        The external result claims success, but the Payment Core lacks a
        stable provider identity required for reconciliation/audit.
        """

        raise PaymentGatewayError(
            (
                "Gateway verification succeeded without "
                "a gateway reference."
            ),
            details={
                "gateway": result.gateway.value,
                "operation": "verify",
                "payment_id": payment.pk,
            },
            retryable=False,
        )

    # ------------------------------------
    # Optional gateway transaction identity
    # ------------------------------------
    #
    # gateway_transaction_id is optional at the current contract level.
    # If the provider supplies it, it is available as part of the typed
    # result and can be persisted by a future Payment repository contract.
    # Verification does not invent one when the provider does not return it.
    #
    _ = gateway_transaction_id

    # ------------------------------------
    # Callback/reference reconciliation
    # ------------------------------------

    normalized_ref_id = _normalize_optional(
        ref_id,
    )

    if (
        normalized_ref_id
        and normalized_ref_id != gateway_reference
    ):
        raise PaymentInvariantViolation(
            "Gateway reference does not match the verification result."
        )

    # ------------------------------------
    # Gateway financial snapshot validation
    # ------------------------------------

    if result.amount is not None:
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
                (
                    "Gateway verification financial "
                    "snapshot mismatch."
                )
            ) from exc

    # ------------------------------------
    # Gateway currency validation
    # ------------------------------------

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
                (
                    "Gateway verification currency "
                    "does not match the Payment currency."
                )
            )

    # ------------------------------------
    # Domain transition
    # ------------------------------------

    payment.succeed()

    # ------------------------------------
    # Payment persistence
    # ------------------------------------

    PaymentRepository.save(
        payment,
        update_fields=(
            "status",
        ),
    )

    # ------------------------------------
    # Order payment confirmation
    # ------------------------------------

    confirm_order_payment(
        order_id=payment.order_id,
    )

    return payment


def _normalize_optional(
    value: Any,
) -> str:
    """
    Normalize an optional textual gateway value.
    Empty values become an empty string.
    No provider-specific interpretation is performed here.
    """

    return str(
        value or "",
    ).strip()

