# core/payment/services/refund.py

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction

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
from payment.providers.base import GatewayRefundResult
from payment.repositories.payment_repository import PaymentRepository
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

        transaction.atomic()
            ->
        lock Payment
            ->
        resolve idempotency
            ->
        authorize cumulative refund
            ->
        create Refund
            ->
        execute gateway
            ->
        persist Refund result
            ->
        synchronize fully-refunded Payment
            ->
        commit

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
        Execute one refund request.

        The Payment row remains locked for the complete cumulative
        authorization and refund state transition workflow.

        ``actor`` is accepted as application context for compatibility with
        the surrounding application layer. Actor/audit persistence remains
        outside this service.
        """

        del actor

        normalized_amount = cls._normalize_amount(amount)
        normalized_key = cls._normalize_idempotency_key(
            idempotency_key,
        )

        with transaction.atomic():
            # ================================
            # Canonical Payment lock
            # ================================

            payment = PaymentRepository.get_for_update(
                payment_id,
            )

            # ================================
            # Idempotency
            # ================================

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

            # ================================
            # Payment eligibility
            # ================================

            PaymentPolicy.can_refund(
                payment,
            )

            # ================================
            # V1 currency contract
            # ================================

            cls._validate_v1_currency(
                payment.currency,
            )

            # ================================
            # Cumulative successful refund authorization
            # ================================

            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk,
                )
            )

            cls._validate_successful_refund_total(
                successful_refunded=successful_refunded,
                payment_amount=payment.amount,
            )

            remaining_refundable = (
                payment.amount - successful_refunded
            )

            cls._validate_requested_amount(
                amount=normalized_amount,
                remaining_refundable=remaining_refundable,
            )

            # ================================
            # Immutable Refund snapshot
            # ================================

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
                The database uniqueness constraint is authoritative.

                An IntegrityError is treated as an idempotency race only
                when the requested idempotency identity can actually be
                resolved.

                Unrelated integrity failures are re-raised.
                """

                existing = (
                    RefundRepository.find_by_idempotency_key_for_update(
                        normalized_key,
                    )
                )

                if existing is None:
                    raise

                cls._validate_idempotent_request(
                    refund=existing,
                    payment=payment,
                    amount=normalized_amount,
                )

                return existing

            # ================================
            # Domain financial validation
            # ================================

            refund.validate_against_payment(
                payment_amount=payment.amount,
                payment_currency=payment.currency,
            )

            # ================================
            # Request observability
            # ================================

            RefundRepository.save(
                refund,
                update_fields=(
                    "ip_address",
                    "user_agent",
                    "meta",
                ),
            )

            # ================================
            # Gateway execution
            # ================================

            try:
                result = GatewayService.refund(
                    payment=payment,
                    refund=refund,
                )

            except PaymentGatewayNotSupportedError:
                """
                Unsupported refund capability is deterministic.

                The selected historical gateway cannot perform this
                operation. No external financial uncertainty exists.
                """

                return cls._mark_failed(
                    refund=refund,
                    reason=(
                        "Gateway refund operation is not supported."
                    ),
                )

            except PaymentGatewayError as exc:
                """
                GatewayService exposes gateway communication/integration
                failures through the payment-specific exception contract.

                A PaymentGatewayError does not by itself prove that the
                refund was rejected.

                Therefore the Refund remains PENDING and reconcilable.
                """

                return cls._register_gateway_exception(
                    refund=refund,
                    exc=exc,
                )

            # ================================
            # Gateway result contract
            # ================================

            if not isinstance(
                result,
                GatewayRefundResult,
            ):
                """
                The provider violated the typed gateway contract.

                We cannot safely classify this as a financial rejection.
                Keep the Refund pending so reconciliation can determine the
                external outcome.
                """

                return cls._register_gateway_evidence(
                    refund=refund,
                    response_code="INVALID_RESULT",
                    gateway_message=(
                        "Gateway returned an invalid refund result."
                    ),
                )

            # ================================
            # Definitive gateway failure
            # ================================

            if not result.success:
                return cls._mark_failed(
                    refund=refund,
                    reason=cls._gateway_failure_reason(
                        result,
                    ),
                    response_code=cls._gateway_response_code(
                        result,
                    ),
                    gateway_message=cls._gateway_message(
                        result,
                    ),
                    latency_ms=cls._gateway_latency(
                        result,
                    ),
                )

            # ================================
            # Gateway SUCCESS identity
            # ================================

            gateway_reference = cls._normalize_optional(
                result.gateway_reference,
            )

            gateway_transaction_id = cls._normalize_optional(
                result.gateway_transaction_id,
            )

            if not (
                gateway_reference
                or gateway_transaction_id
            ):
                """
                The provider claims success but supplied no trusted external
                identity.

                This is NOT safe to classify as SUCCESS.

                It is also NOT safe to classify as confirmed FAILURE because
                the gateway may already have processed the refund.

                Therefore the Refund remains PENDING and is eligible for
                reconciliation.
                """

                return cls._register_gateway_evidence(
                    refund=refund,
                    response_code=cls._gateway_response_code(
                        result,
                    ),
                    gateway_message=(
                        "Gateway reported refund success without "
                        "a trusted gateway identity."
                    ),
                )

            # ================================
            # Domain SUCCESS transition
            # ================================

            refund.mark_success(
                gateway_reference=gateway_reference,
                gateway_transaction_id=gateway_transaction_id,
                response_code=cls._gateway_response_code(
                    result,
                ),
                gateway_message=cls._gateway_message(
                    result,
                ),
                latency_ms=cls._gateway_latency(
                    result,
                ),
            )

            RefundRepository.save_success(
                refund,
            )

            # ================================
            # Recalculate authoritative successful refund total
            # ================================

            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk,
                )
            )

            cls._validate_successful_refund_total(
                successful_refunded=successful_refunded,
                payment_amount=payment.amount,
            )

            # ================================
            # Fully refunded Payment
            # ================================

            if successful_refunded == payment.amount:
                payment.refund()

                PaymentRepository.save_refund_state(
                    payment,
                )

            return refund

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