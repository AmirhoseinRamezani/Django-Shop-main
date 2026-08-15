# core/payment/services/refund.py

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction

from payment.enums import Currency, RefundStatus
from payment.exceptions import (
    PaymentCurrencyMismatchError,
    PaymentGatewayIdentityConflictError,
    PaymentGatewayNotSupportedError,
    PaymentInvariantViolation,
    PaymentRefundAmountInvalidError,
)
from payment.models.refund import Refund
from payment.policies import PaymentPolicy
from payment.repositories.payment_repository import PaymentRepository
from payment.repositories.refund_repository import RefundRepository
from payment.services.gateway_service import GatewayService


class RefundService:
    """
    Application service for Payment refunds.

    Responsibilities
    ----------------
    - transaction boundary
    - Payment row locking
    - idempotency resolution
    - cumulative refund authorization
    - gateway orchestration
    - Refund domain transitions
    - Refund persistence
    - fully-refunded Payment mutation

    Non-responsibilities
    --------------------
    - low-level ORM queries
    - Refund state-machine implementation
    - gateway HTTP implementation
    - pure business policy implementation
    """

    @classmethod
    def refund(
        cls,
        *,
        payment_id: int,
        amount: Decimal,
        idempotency_key: str,
        reason,
        reason_detail: str = "",
        actor: Any = None,
        ip_address: str | None = None,
        user_agent: str = "",
        meta: dict[str, Any] | None = None,
    ) -> Refund:
        """
        Execute a refund request.

        Payment is the canonical synchronization point for cumulative
        refund authorization.

        The complete financial authorization workflow runs while the
        Payment row is locked.

        A gateway rejection becomes a persisted FAILED Refund.

        A gateway capability/integration error is propagated only after
        the Refund failure state has been persisted safely.
        """

        normalized_amount = cls._normalize_amount(
            amount
        )

        normalized_key = cls._normalize_key(
            idempotency_key
        )

        with transaction.atomic():
            payment = PaymentRepository.get_for_update(
                payment_id
            )

            # ------------------------------------
            # Idempotency
            # ------------------------------------

            existing = (
                RefundRepository
                .find_by_idempotency_key_for_update(
                    normalized_key
                )
            )

            if existing is not None:
                cls._validate_idempotent_request(
                    refund=existing,
                    payment=payment,
                    amount=normalized_amount,
                    currency=payment.currency,
                )

                return existing

            # ------------------------------------
            # Payment eligibility
            # ------------------------------------

            PaymentPolicy.can_refund(
                payment
            )

            # ------------------------------------
            # V1 currency contract
            # ------------------------------------

            if payment.currency != Currency.IRR:
                raise PaymentCurrencyMismatchError(
                    "Only IRR refunds are supported in V1."
                )

            # ------------------------------------
            # Cumulative successful refund authorization
            #
            # Payment is already locked.
            #
            # Therefore another refund workflow for the same Payment
            # cannot calculate its authorization against the same
            # stale Payment state.
            # ------------------------------------

            successful_refunded = (
                RefundRepository
                .successful_amount_for_payment(
                    payment.pk
                )
            )

            if successful_refunded < Decimal("0"):
                raise PaymentInvariantViolation(
                    "Successful refund total cannot be negative."
                )

            if successful_refunded > payment.amount:
                raise PaymentInvariantViolation(
                    (
                        "Existing successful refunds already exceed "
                        "the Payment amount."
                    )
                )

            remaining_refundable = (
                payment.amount
                - successful_refunded
            )

            if remaining_refundable <= Decimal("0"):
                raise PaymentRefundAmountInvalidError(
                    "Payment has no refundable balance remaining."
                )

            if normalized_amount > remaining_refundable:
                raise PaymentRefundAmountInvalidError(
                    (
                        "Refund amount exceeds the remaining "
                        "refundable balance."
                    )
                )

            # ------------------------------------
            # Create immutable Refund snapshot
            # ------------------------------------

            try:
                refund = RefundRepository.create(
                    payment=payment,
                    amount=normalized_amount,
                    currency=payment.currency,
                    idempotency_key=normalized_key,
                    reason=reason,
                    reason_detail=reason_detail,
                    status=RefundStatus.PENDING,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    meta=meta or {},
                )

            except IntegrityError:
                """
                Database uniqueness is authoritative.

                The expected race is the idempotency-key uniqueness
                conflict. We resolve that explicitly.

                Any unrelated constraint violation is re-raised.
                """

                existing = (
                    RefundRepository
                    .find_by_idempotency_key_for_update(
                        normalized_key
                    )
                )

                if existing is None:
                    raise

                cls._validate_idempotent_request(
                    refund=existing,
                    payment=payment,
                    amount=normalized_amount,
                    currency=payment.currency,
                )

                return existing

            # ------------------------------------
            # Domain validation
            # ------------------------------------

            refund.validate_against_payment(
                payment_amount=payment.amount,
                payment_currency=payment.currency,
            )

            RefundRepository.save(
                refund,
                update_fields=(
                    "ip_address",
                    "user_agent",
                    "meta",
                ),
            )

            # ------------------------------------
            # Gateway execution
            # ------------------------------------

            try:
                result = GatewayService.refund(
                    payment=payment,
                    refund=refund,
                )

            except PaymentGatewayNotSupportedError as exc:
                """
                Provider capability is explicitly unsupported.

                This is a deterministic terminal failure for the
                current Refund request, not a successful refund.

                We persist FAILED and do not re-raise, because the
                Refund itself is now the authoritative financial
                record of this request.
                """

                cls._mark_failed(
                    refund=refund,
                    reason="Gateway refund operation is not supported.",
                )

                return refund

            except Exception as exc:
                """
                IMPORTANT:

                Do not mark FAILED and then re-raise from the same
                atomic transaction.

                Doing so would rollback the FAILED transition.

                For an exception whose financial outcome is unknown,
                keeping the Refund PENDING is safer than falsely
                recording FAILED.

                The pending Refund can later be reconciled.
                """

                cls._register_gateway_exception(
                    refund=refund,
                    exc=exc,
                )

                return refund

            # ------------------------------------
            # Gateway result classification
            # ------------------------------------

            if not cls._gateway_succeeded(
                result
            ):
                cls._mark_failed(
                    refund=refund,
                    reason=cls._gateway_failure_reason(
                        result
                    ),
                    response_code=cls._gateway_response_code(
                        result
                    ),
                    gateway_message=cls._gateway_message(
                        result
                    ),
                    latency_ms=cls._gateway_latency(
                        result
                    ),
                )

                return refund

            # ------------------------------------
            # Gateway SUCCESS must have identity
            # ------------------------------------

            gateway_reference = (
                cls._gateway_reference(
                    result
                )
            )

            gateway_transaction_id = (
                cls._gateway_transaction_id(
                    result
                )
            )

            if not (
                gateway_reference
                or gateway_transaction_id
            ):
                """
                A successful financial result without any trusted
                gateway identity cannot safely become SUCCESS.
                """

                cls._mark_failed(
                    refund=refund,
                    reason=(
                        "Gateway returned success without "
                        "a gateway refund identity."
                    ),
                    response_code=cls._gateway_response_code(
                        result
                    ),
                    gateway_message=cls._gateway_message(
                        result
                    ),
                    latency_ms=cls._gateway_latency(
                        result
                    ),
                )

                return refund

            # ------------------------------------
            # SUCCESS transition
            # ------------------------------------

            refund.mark_success(
                gateway_reference=gateway_reference,
                gateway_transaction_id=(
                    gateway_transaction_id
                ),
                response_code=cls._gateway_response_code(
                    result
                ),
                gateway_message=cls._gateway_message(
                    result
                ),
                latency_ms=cls._gateway_latency(
                    result
                ),
            )

            RefundRepository.save_success(
                refund
            )

            # ------------------------------------
            # Recalculate cumulative successful refunds
            #
            # Payment remains locked.
            # ------------------------------------

            successful_refunded = (
                RefundRepository
                .successful_amount_for_payment(
                    payment.pk
                )
            )

            if successful_refunded > payment.amount:
                raise PaymentInvariantViolation(
                    (
                        "Successful refunds exceed the Payment "
                        "amount after successful refund persistence."
                    )
                )

            # ------------------------------------
            # Fully refunded Payment
            # ------------------------------------

            if successful_refunded == payment.amount:
                payment.refund()

                PaymentRepository.save_refund_state(
                    payment
                )

            return refund

    # ================================
    # Idempotency
    # ================================

    @staticmethod
    def _validate_idempotent_request(
        *,
        refund: Refund,
        payment,
        amount: Decimal,
        currency: str,
    ) -> None:
        """
        Validate that an idempotency key is being reused for the same
        financial request.
        """

        if refund.payment_id != payment.pk:
            raise PaymentInvariantViolation(
                "Idempotency key belongs to another Payment."
            )

        if refund.amount != amount:
            raise PaymentRefundAmountInvalidError(
                (
                    "Idempotency key was already used with a "
                    "different refund amount."
                )
            )

        if refund.currency != currency:
            raise PaymentCurrencyMismatchError(
                (
                    "Idempotency key was already used with a "
                    "different refund currency."
                )
            )

    # ================================
    # Gateway exception handling
    # ================================

    @staticmethod
    def _register_gateway_exception(
        *,
        refund: Refund,
        exc: Exception,
    ) -> Refund:
        """
        Persist safe gateway evidence without changing the financial
        lifecycle.

        A transport exception does not prove that the gateway rejected
        the refund.

        Therefore the Refund remains PENDING and can be reconciled.
        """

        refund.register_gateway_response(
            response_code=exc.__class__.__name__,
            gateway_message=(
                "Gateway refund execution did not return "
                "a definitive result."
            ),
        )

        RefundRepository.save_gateway_evidence(
            refund
        )

        return refund

    # ================================
    # Failed gateway operation
    # ================================

    @staticmethod
    def _mark_failed(
        *,
        refund: Refund,
        reason: str,
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> Refund:
        """
        Persist a terminal FAILED Refund.

        This method MUST be called inside the active transaction when
        the caller intends to commit the FAILED state.
        """

        if refund.is_terminal:
            return refund

        refund.mark_failed(
            reason=reason,
            response_code=response_code,
            gateway_message=gateway_message,
            latency_ms=latency_ms,
        )

        RefundRepository.save_failure(
            refund
        )

        return refund

    # ================================
    # Gateway normalization
    # ================================

    @staticmethod
    def _gateway_succeeded(
        result: Any,
    ) -> bool:
        if result is None:
            return False

        if isinstance(result, dict):
            return bool(
                result.get("success")
            )

        return bool(
            getattr(
                result,
                "success",
                False,
            )
        )

    @staticmethod
    def _gateway_reference(
        result: Any,
    ) -> str:
        if result is None:
            return ""

        if isinstance(result, dict):
            value = (
                result.get("gateway_reference")
                or result.get("ref_id")
                or result.get("reference")
            )
        else:
            value = (
                getattr(
                    result,
                    "gateway_reference",
                    "",
                )
                or getattr(
                    result,
                    "ref_id",
                    "",
                )
                or getattr(
                    result,
                    "reference",
                    "",
                )
            )

        return str(
            value or ""
        ).strip()

    @staticmethod
    def _gateway_transaction_id(
        result: Any,
    ) -> str:
        if result is None:
            return ""

        if isinstance(result, dict):
            value = (
                result.get(
                    "gateway_transaction_id"
                )
                or result.get(
                    "transaction_id"
                )
            )
        else:
            value = (
                getattr(
                    result,
                    "gateway_transaction_id",
                    "",
                )
                or getattr(
                    result,
                    "transaction_id",
                    "",
                )
            )

        return str(
            value or ""
        ).strip()

    @staticmethod
    def _gateway_response_code(
        result: Any,
    ) -> str:
        if result is None:
            return ""

        if isinstance(result, dict):
            value = (
                result.get("response_code")
                or result.get("code")
            )
        else:
            value = (
                getattr(
                    result,
                    "response_code",
                    "",
                )
                or getattr(
                    result,
                    "code",
                    "",
                )
            )

        return str(
            value or ""
        ).strip()

    @staticmethod
    def _gateway_message(
        result: Any,
    ) -> str:
        if result is None:
            return ""

        if isinstance(result, dict):
            value = (
                result.get("gateway_message")
                or result.get("message")
            )
        else:
            value = (
                getattr(
                    result,
                    "gateway_message",
                    "",
                )
                or getattr(
                    result,
                    "message",
                    "",
                )
            )

        return str(
            value or ""
        ).strip()[:255]

    @staticmethod
    def _gateway_failure_reason(
        result: Any,
    ) -> str:
        if result is None:
            return "Gateway refund returned no result."

        if isinstance(result, dict):
            value = (
                result.get("failure_reason")
                or result.get("message")
                or result.get("error")
                or result.get("code")
            )
        else:
            value = (
                getattr(
                    result,
                    "failure_reason",
                    "",
                )
                or getattr(
                    result,
                    "message",
                    "",
                )
                or getattr(
                    result,
                    "error",
                    "",
                )
                or getattr(
                    result,
                    "code",
                    "",
                )
            )

        normalized = str(
            value or ""
        ).strip()

        return (
            normalized[:255]
            if normalized
            else "Gateway refund failed."
        )

    @staticmethod
    def _gateway_latency(
        result: Any,
    ) -> int | None:
        if result is None:
            return None

        if isinstance(result, dict):
            value = result.get(
                "latency_ms"
            )
        else:
            value = getattr(
                result,
                "latency_ms",
                None,
            )

        if value is None:
            return None

        try:
            normalized = int(value)
        except (
            TypeError,
            ValueError,
        ):
            return None

        return max(
            0,
            normalized,
        )

    # ================================
    # Input normalization
    # ================================

    @staticmethod
    def _normalize_amount(
        amount: Decimal,
    ) -> Decimal:
        try:
            normalized = Decimal(
                str(amount)
            )
        except (
            TypeError,
            ValueError,
            ArithmeticError,
        ) as exc:
            raise PaymentRefundAmountInvalidError(
                "Invalid refund amount."
            ) from exc

        if normalized <= Decimal("0"):
            raise PaymentRefundAmountInvalidError(
                "Refund amount must be greater than zero."
            )
        return normalized

    @staticmethod
    def _normalize_key(
        value: str,
    ) -> str:
        normalized = str(
            value or ""
        ).strip()

        if not normalized:
            raise PaymentInvariantViolation(
                "Refund idempotency key is required."
            )
        return normalized

    @staticmethod
    def _safe_exception_reason(
        exc: Exception,
    ) -> str:
        """
        Keep this helper available for future reconciliation/logging
        workflows.

        Do not persist arbitrary exception strings because external
        provider exceptions may contain request payloads or secrets.
        """
        name = exc.__class__.__name__

        return (
            f"Gateway refund execution failed: {name}"
        )[:255]