# core/payment/services/refund.py

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction

from payment.enums import Currency, RefundStatus
from payment.exceptions import (
    PaymentCurrencyMismatchError,
    PaymentGatewayError,
    PaymentGatewayNotSupportedError,
    PaymentInvariantViolation,
    PaymentRefundAmountInvalidError,
)
from payment.models.refund import Refund
from payment.policies import PaymentPolicy
from payment.providers.base import (
    GatewayRefundInquiryResult,
    GatewayRefundResult,
)
from payment.repositories.payment_repository import PaymentRepository
from payment.repositories.payment_attempt_repository import PaymentAttemptRepository
from payment.repositories.refund_repository import RefundRepository
from payment.services.gateway_service import GatewayService


class RefundService:
    """
    Application service for the Payment refund workflow.

    Responsibilities
    ----------------
    - transaction boundary
    - canonical Payment locking
    - idempotency resolution
    - cumulative refund authorization
    - Refund creation
    - gateway orchestration
    - Refund domain transitions
    - Refund persistence
    - fully-refunded Payment synchronization

    Non-responsibilities
    --------------------
    - Refund state-machine rules
    - low-level ORM queries
    - repository locking implementation
    - gateway HTTP/protocol implementation
    - provider-specific response parsing
    - Order mutation
    - event publication
    - raw gateway payload persistence

    Concurrency contract
    --------------------
    The Payment row is the canonical synchronization point.

    Refund reservation is committed before gateway execution. Gateway I/O
    never runs while the Payment row is locked.

        Phase A: lock Payment -> authorize -> create PENDING Refund -> commit
        Phase B: execute gateway
        Phase C: lock Payment + exact Refund -> finalize -> commit

    Gateway outcome contract
    ------------------------
    Confirmed rejection:
        -> Refund.FAILED

    Confirmed success + trusted gateway identity:
        -> Refund.SUCCESS

    Unknown external outcome:
        -> Refund.PENDING

    A transport/infrastructure exception must never be interpreted as
    confirmed financial failure because the gateway may have processed the
    refund before the response was lost.

    V1 financial contract
    ---------------------
    Refunds currently operate on IRR only.

    V2 concerns such as:
        - fractional currencies
        - multi-currency
        - FX
        - Money/Quote
        - crypto assets

    intentionally do not belong here yet.
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
        Reserve one refund request durably, execute the gateway outside the
        database critical section, then finalize the exact Refund.

        A newly created PENDING Refund owns the financial reservation.
        Existing PENDING refunds are returned to the caller and are not
        executed again by an ordinary application retry.
        """

        del actor

        normalized_amount = cls._normalize_amount(amount)
        normalized_key = cls._normalize_idempotency_key(idempotency_key)

        with transaction.atomic():
            payment = PaymentRepository.get_for_update(payment_id)

            existing = (
                RefundRepository.find_by_idempotency_key_for_update(
                    normalized_key,
                )
            )

            if existing is not None:
                cls._validate_idempotent_request(
                    refund=existing,
                    payment=payment,
                    amount=normalized_amount,
                )
                return existing

            PaymentPolicy.can_refund(payment)

            attempt = (
                PaymentAttemptRepository
                .latest_successful_for_payment_for_update(
                    payment.pk,
                )
            )

            if attempt is None:
                raise PaymentInvariantViolation(
                    "A refundable Payment must have a successful PaymentAttempt."
                )

            reserved_refunded = (
                RefundRepository.reserved_amount_for_payment(
                    payment.pk,
                )
            )

            if reserved_refunded > payment.amount:
                raise PaymentInvariantViolation(
                    "Reserved refund amount exceeds the Payment amount."
                )

            remaining_refundable = payment.amount - reserved_refunded

            cls._validate_requested_amount(
                amount=normalized_amount,
                remaining_refundable=remaining_refundable,
            )

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

        try:
            result = GatewayService.refund(
                payment=payment,
                attempt=attempt,
                refund=refund,
            )
        except PaymentGatewayNotSupportedError:
            return cls._finalize_failure(
                payment_id=payment_id,
                refund_id=refund.pk,
                reason="Gateway refund operation is not supported.",
            )
        except PaymentGatewayError as exc:
            return cls._record_pending_gateway_error(
                payment_id=payment_id,
                refund_id=refund.pk,
                exc=exc,
            )

        if not isinstance(result, GatewayRefundResult):
            return cls._record_pending_gateway_evidence(
                payment_id=payment_id,
                refund_id=refund.pk,
                response_code="INVALID_RESULT",
                gateway_message="Gateway returned an invalid refund result.",
            )

        if not result.success:
            return cls._finalize_failure(
                payment_id=payment_id,
                refund_id=refund.pk,
                reason=cls._gateway_failure_reason(result),
                response_code=cls._gateway_response_code(result),
                gateway_message=cls._gateway_message(result),
                latency_ms=cls._gateway_latency(result),
            )

        gateway_reference = cls._normalize_optional(
            result.gateway_reference,
        )
        gateway_transaction_id = cls._normalize_optional(
            result.gateway_transaction_id,
        )

        if not (gateway_reference or gateway_transaction_id):
            return cls._record_pending_gateway_evidence(
                payment_id=payment_id,
                refund_id=refund.pk,
                response_code=cls._gateway_response_code(result),
                gateway_message=(
                    "Gateway reported refund success without "
                    "a trusted gateway identity."
                ),
            )

        return cls._finalize_success(
            payment_id=payment_id,
            refund_id=refund.pk,
            gateway_reference=gateway_reference,
            gateway_transaction_id=gateway_transaction_id,
            response_code=cls._gateway_response_code(result),
            gateway_message=cls._gateway_message(result),
            latency_ms=cls._gateway_latency(result),
        )


    @classmethod
    def reconcile_pending_refund(
        cls,
        *,
        refund_id: int,
    ) -> Refund:
        """
        Reconcile an unresolved PENDING Refund using provider inquiry.

        This is a recovery operation, not a refund retry. It never calls
        the refund execution endpoint again.

        Providers without refund inquiry support remain an explicit
        operational blocker and the Refund stays PENDING.
        """

        with transaction.atomic():
            payment = PaymentRepository.get_for_update(
                RefundRepository.get(refund_id).payment_id,
            )
            refund = RefundRepository.get_for_update(
                refund_id,
            )

            if refund.payment_id != payment.pk:
                raise PaymentInvariantViolation(
                    "Refund does not belong to the locked Payment."
                )

            if refund.is_terminal:
                return refund

            attempt = (
                PaymentAttemptRepository
                .latest_successful_for_payment_for_update(
                    payment.pk,
                )
            )

        try:
            result = GatewayService.inquire_refund(
                payment=payment,
                attempt=attempt,
                refund=refund,
            )
        except PaymentGatewayNotSupportedError:
            raise
        except PaymentGatewayError as exc:
            return cls._record_pending_gateway_error(
                payment_id=payment.pk,
                refund_id=refund.pk,
                exc=exc,
            )

        if not isinstance(result, GatewayRefundInquiryResult):
            return cls._record_pending_gateway_evidence(
                payment_id=payment.pk,
                refund_id=refund.pk,
                response_code="INVALID_RESULT",
                gateway_message=(
                    "Gateway returned an invalid refund inquiry result."
                ),
            )

        if result.status == RefundStatus.PENDING:
            return cls._record_pending_gateway_evidence(
                payment_id=payment.pk,
                refund_id=refund.pk,
                response_code=cls._gateway_inquiry_response_code(result),
                gateway_message=cls._gateway_inquiry_message(result),
            )

        if result.status == RefundStatus.FAILED:
            return cls._finalize_failure(
                payment_id=payment.pk,
                refund_id=refund.pk,
                reason=cls._gateway_inquiry_failure_reason(result),
                response_code=cls._gateway_inquiry_response_code(result),
                gateway_message=cls._gateway_inquiry_message(result),
            )

        gateway_reference = cls._normalize_optional(
            result.gateway_reference,
        )
        gateway_transaction_id = cls._normalize_optional(
            result.gateway_transaction_id,
        )

        if not (gateway_reference or gateway_transaction_id):
            return cls._record_pending_gateway_evidence(
                payment_id=payment.pk,
                refund_id=refund.pk,
                response_code=cls._gateway_inquiry_response_code(result),
                gateway_message=(
                    "Gateway confirmed refund success without "
                    "a trusted gateway identity."
                ),
            )

        return cls._finalize_success(
            payment_id=payment.pk,
            refund_id=refund.pk,
            gateway_reference=gateway_reference,
            gateway_transaction_id=gateway_transaction_id,
            response_code=cls._gateway_inquiry_response_code(result),
            gateway_message=cls._gateway_inquiry_message(result),
            latency_ms=None,
        )

    @classmethod
    def _finalize_success(
        cls,
        *,
        payment_id: int,
        refund_id: int,
        gateway_reference: str,
        gateway_transaction_id: str,
        response_code: str,
        gateway_message: str,
        latency_ms: int | None,
    ) -> Refund:
        with transaction.atomic():
            payment = PaymentRepository.get_for_update(payment_id)
            refund = RefundRepository.get_for_update(refund_id)

            if refund.payment_id != payment.pk:
                raise PaymentInvariantViolation(
                    "Refund does not belong to the locked Payment."
                )

            if refund.is_success:
                cls._sync_payment_refund_state(
                    payment=payment,
                )
                return refund

            if refund.is_failed:
                return refund

            refund.mark_success(
                gateway_reference=gateway_reference,
                gateway_transaction_id=gateway_transaction_id,
                response_code=response_code,
                gateway_message=gateway_message,
                latency_ms=latency_ms,
            )

            RefundRepository.save_success(refund)

            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk,
                )
            )

            cls._validate_successful_refund_total(
                successful_refunded=successful_refunded,
                payment_amount=payment.amount,
            )

            cls._sync_payment_refund_state(
                payment=payment,
            )

            return refund

    @classmethod
    def _finalize_failure(
        cls,
        *,
        payment_id: int,
        refund_id: int,
        reason: str,
        response_code: str = "",
        gateway_message: str = "",
        latency_ms: int | None = None,
    ) -> Refund:
        with transaction.atomic():
            payment = PaymentRepository.get_for_update(payment_id)
            refund = RefundRepository.get_for_update(refund_id)

            if refund.payment_id != payment.pk:
                raise PaymentInvariantViolation(
                    "Refund does not belong to the locked Payment."
                )

            if refund.is_terminal:
                return refund

            refund.mark_failed(
                reason=reason,
                response_code=response_code,
                gateway_message=gateway_message,
                latency_ms=latency_ms,
            )

            RefundRepository.save_failure(refund)
            return refund

    @classmethod
    def _record_pending_gateway_error(
        cls,
        *,
        payment_id: int,
        refund_id: int,
        exc: PaymentGatewayError,
    ) -> Refund:
        return cls._record_pending_gateway_evidence(
            payment_id=payment_id,
            refund_id=refund_id,
            response_code=exc.__class__.__name__,
            gateway_message=(
                "Gateway refund execution did not return "
                "a definitive result."
            ),
        )

    @classmethod
    def _record_pending_gateway_evidence(
        cls,
        *,
        payment_id: int,
        refund_id: int,
        response_code: str = "",
        gateway_message: str = "",
    ) -> Refund:
        with transaction.atomic():
            payment = PaymentRepository.get_for_update(payment_id)
            refund = RefundRepository.get_for_update(refund_id)

            if refund.payment_id != payment.pk:
                raise PaymentInvariantViolation(
                    "Refund does not belong to the locked Payment."
                )

            if refund.is_terminal:
                return refund

            refund.register_gateway_response(
                response_code=response_code,
                gateway_message=gateway_message,
            )

            RefundRepository.save_gateway_evidence(refund)
            return refund

    @staticmethod
    def _sync_payment_refund_state(*, payment) -> None:
        successful_refunded = (
            RefundRepository.successful_amount_for_payment(
                payment.pk,
            )
        )

        if successful_refunded > payment.amount:
            raise PaymentInvariantViolation(
                "Successful refund total exceeds the Payment amount."
            )

        should_be_refunded = successful_refunded == payment.amount

        if payment.is_refunded == should_be_refunded:
            return

        if should_be_refunded:
            payment.refund()
        else:
            payment.is_refunded = False

        PaymentRepository.save_refund_state(payment)

    # ============================
    # IDEMPOTENCY
    # ============================

    @staticmethod
    def _validate_idempotent_request(
        *,
        refund: Refund,
        payment,
        amount: Decimal,
    ) -> None:
        """
        Validate reuse of an existing refund idempotency key.

        The same idempotency key is valid only for the same financial
        operation.

        The database guarantees global uniqueness of the key. Therefore,
        using the same key for another Payment is an application-level
        conflict.
        """

        if refund.payment_id != payment.pk:
            raise PaymentInvariantViolation(
                "Refund idempotency key belongs to another Payment.",
            )

        if refund.amount != amount:
            raise PaymentRefundAmountInvalidError(
                (
                    "Refund idempotency key was already used with "
                    "a different refund amount."
                ),
            )

        if refund.currency != payment.currency:
            raise PaymentCurrencyMismatchError(
                (
                    "Refund idempotency key was already used with "
                    "a different refund currency."
                ),
            )

    # ============================
    # FINANCIAL VALIDATION
    # ============================

    @staticmethod
    def _validate_v1_currency(
        currency: str,
    ) -> None:
        """
        Enforce the V1 IRR-only financial contract.

        V1 intentionally excludes:
        - FX conversion
        - multi-currency arithmetic
        - fractional currency units
        - exchange-rate snapshots

        These belong to V2 and should extend this contract rather than
        forcing a rewrite.
        """

        if currency != Currency.IRR:
            raise PaymentCurrencyMismatchError(
                "Only IRR refunds are supported in V1.",
            )

    @staticmethod
    def _validate_successful_refund_total(
        *,
        successful_refunded: Decimal,
        payment_amount: Decimal,
    ) -> None:
        """
        Validate the authoritative persisted successful-refund aggregate.
        This is an integrity assertion, not the primary authorization rule.
        """

        if successful_refunded < Decimal("0"):
            raise PaymentInvariantViolation(
                "Successful refund total cannot be negative.",
            )

        if successful_refunded > payment_amount:
            raise PaymentInvariantViolation(
                (
                    "Existing successful refunds already exceed "
                    "the Payment amount."
                ),
            )

    @staticmethod
    def _validate_requested_amount(
        *,
        amount: Decimal,
        remaining_refundable: Decimal,
    ) -> None:
        """
        Validate the requested refund against the currently available
        refundable balance.
        """

        if remaining_refundable <= Decimal("0"):
            raise PaymentRefundAmountInvalidError(
                "Payment has no refundable balance remaining.",
            )

        if amount > remaining_refundable:
            raise PaymentRefundAmountInvalidError(
                (
                    "Refund amount exceeds the remaining "
                    "refundable balance."
                ),
            )

    # ============================
    # UNKNOWN GATEWAY OUTCOME
    # ============================

    @staticmethod
    def _register_gateway_exception(
        *,
        refund: Refund,
        exc: PaymentGatewayError,
    ) -> Refund:
        """
        Preserve safe evidence for an unknown gateway outcome.

        Exception text is deliberately not persisted because provider
        exceptions may contain sensitive operational information.

        GatewayLog/reconciliation infrastructure remains responsible for
        detailed technical evidence.

        Refund remains PENDING.
        """

        return RefundService._register_gateway_evidence(
            refund=refund,
            response_code=exc.__class__.__name__,
            gateway_message=(
                "Gateway refund execution did not return "
                "a definitive result."
            ),
        )

    @staticmethod
    def _register_gateway_evidence(
        *,
        refund: Refund,
        response_code: str = "",
        gateway_message: str = "",
    ) -> Refund:
        """
        Persist bounded non-terminal gateway evidence.

        The Refund domain model intentionally allows gateway evidence to be
        updated only while the Refund is PENDING.
        """

        refund.register_gateway_response(
            response_code=response_code,
            gateway_message=gateway_message,
        )

        RefundRepository.save_gateway_evidence(
            refund,
        )

        return refund

    # ============================
    # TERMINAL FAILURE
    # ============================

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
        Persist a deterministic terminal FAILED transition.
        This method is reserved for confirmed failures.

        It must NOT be used for:
        - timeout
        - connection reset
        - lost response
        - provider unavailability
        - unknown external outcome
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
            refund,
        )

        return refund

    # ============================
    # GATEWAY RESULT NORMALIZATION
    # ============================


    @staticmethod
    def _gateway_inquiry_response_code(
        result: GatewayRefundInquiryResult,
    ) -> str:
        return RefundService._normalize_optional(
            result.response_code,
        )[:64]

    @staticmethod
    def _gateway_inquiry_message(
        result: GatewayRefundInquiryResult,
    ) -> str:
        return RefundService._normalize_optional(
            result.message,
        )[:255]

    @staticmethod
    def _gateway_inquiry_failure_reason(
        result: GatewayRefundInquiryResult,
    ) -> str:
        message = RefundService._gateway_inquiry_message(result)
        if message:
            return message

        response_code = RefundService._gateway_inquiry_response_code(result)
        if response_code:
            return f"Gateway refund inquiry failed: {response_code}"[:255]

        return "Gateway confirmed refund failure."

    @staticmethod
    def _gateway_response_code(
        result: GatewayRefundResult,
    ) -> str:
        """
        Return a bounded provider-independent response code.
        """

        return RefundService._normalize_optional(
            result.response_code,
        )[:64]

    @staticmethod
    def _gateway_message(
        result: GatewayRefundResult,
    ) -> str:
        """
        Return a bounded provider-independent gateway message.
        """

        return RefundService._normalize_optional(
            result.message,
        )[:255]

    @staticmethod
    def _gateway_failure_reason(
        result: GatewayRefundResult,
    ) -> str:
        """
        Build a deterministic bounded failure reason.
        Raw provider payloads are intentionally excluded.
        """

        message = RefundService._normalize_optional(
            result.message,
        )

        if message:
            return message[:255]

        response_code = RefundService._normalize_optional(
            result.response_code,
        )

        if response_code:
            return (
                f"Gateway refund failed: {response_code}"
            )[:255]

        return "Gateway refund failed."

    @staticmethod
    def _gateway_latency(
        result: GatewayRefundResult,
    ) -> int | None:
        """
        Read optional latency information without coupling V1 to a
        mandatory latency field on GatewayRefundResult.

        Existing gateway DTOs remain compatible.
        """

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

    # ============================
    # INPUT NORMALIZATION
    # ============================

    @staticmethod
    def _normalize_amount(
        amount: Decimal,
    ) -> Decimal:
        """
        Normalize a financial amount without floating-point arithmetic.
        """

        try:
            normalized = Decimal(
                str(amount),
            )
        except (
            TypeError,
            ValueError,
            ArithmeticError,
        ) as exc:
            raise PaymentRefundAmountInvalidError(
                "Invalid refund amount.",
            ) from exc

        if not normalized.is_finite():
            raise PaymentRefundAmountInvalidError(
                "Refund amount must be finite.",
            )

        if normalized <= Decimal("0"):
            raise PaymentRefundAmountInvalidError(
                "Refund amount must be greater than zero.",
            )

        return normalized

    @staticmethod
    def _normalize_idempotency_key(
        value: str,
    ) -> str:
        """
        Normalize and validate the logical refund request identity.
        """

        normalized = str(
            value or "",
        ).strip()

        if not normalized:
            raise PaymentInvariantViolation(
                "Refund idempotency key is required.",
            )

        return normalized

    @staticmethod
    def _normalize_optional(
        value: Any,
    ) -> str:
        """
        Normalize optional textual gateway data.
        Provider-specific interpretation is intentionally excluded.
        """

        return str(
            value or "",
        ).strip()