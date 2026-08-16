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
    This service owns the orchestration boundary for a refund operation:

        - transaction.atomic()
        - canonical Payment locking
        - idempotency reconciliation
        - cumulative refund authorization
        - Refund creation
        - gateway execution
        - Refund domain transitions
        - Refund persistence
        - fully-refunded Payment synchronization

    Non-responsibilities
    --------------------
    This service does not own:

        - Refund state-machine rules
        - low-level ORM queries
        - database locking implementation
        - gateway HTTP/protocol implementation
        - provider-specific response parsing
        - Order mutation
        - event publication
        - raw gateway payload persistence
        - generic idempotency infrastructure

    Concurrency
    -----------
    Payment is the canonical synchronization point for cumulative refund
    authorization.

    The Payment row remains locked for the complete financial workflow,
    including the gateway execution.

    This is intentional in V1.

    Releasing the Payment lock before gateway execution would allow a
    second refund request to authorize against a stale successful-refund
    total while the first refund is still pending.

    Future optimization of this boundary requires an explicit refund
    reservation mechanism and must not be introduced implicitly here.

    Gateway outcome semantics
    -------------------------
    A definitive gateway rejection becomes FAILED.

    A transport/infrastructure/gateway exception with an unknown financial
    outcome leaves the Refund PENDING.

    PENDING is therefore the reconciliation state for an unknown external
    outcome.

    A gateway exception must never be converted into FAILED merely because
    the HTTP/request execution raised an exception. The external gateway
    may have accepted the refund before the connection failed.
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

        The financial workflow is serialized through the Payment row lock.

        The same idempotency key is safely reusable for the same financial
        request. A conflicting reuse raises an application/domain error.

        Parameters
        ----------
        payment_id:
            Primary key of the Payment being refunded.

        amount:
            Refund amount in the Payment currency.

        idempotency_key:
            Stable identity of the logical refund request.

        reason:
            RefundReason enum value.

        reason_detail:
            Optional human-readable explanation.

        actor:
            Reserved application-level actor context. Persistence of the
            actor is intentionally outside the Refund model contract.

        ip_address:
            Request IP address captured as Refund observability context.

        user_agent:
            Request user-agent captured as Refund observability context.

        meta:
            Non-financial application metadata.
        """

        normalized_amount = cls._normalize_amount(amount)
        normalized_key = cls._normalize_idempotency_key(idempotency_key)

        with transaction.atomic():
            payment = PaymentRepository.get_for_update(
                payment_id
            )

            # ------------------------------------
            # Idempotency
            # ------------------------------------
            #
            # Payment is already locked, so the existing Refund is
            # reconciled against the same aggregate snapshot.
            #
            existing = (
                RefundRepository.find_by_idempotency_key_for_update(
                    normalized_key
                )
            )

            if existing is not None:
                cls._validate_idempotent_request(
                    refund=existing,
                    payment=payment,
                    amount=normalized_amount,
                )
                return existing

            # ------------------------------------
            # Payment refund policy
            # ------------------------------------
            PaymentPolicy.can_refund(payment)

            # ------------------------------------
            # V1 currency contract
            # ------------------------------------
            cls._validate_v1_currency(payment.currency)

            # ------------------------------------
            # Cumulative successful refund authorization
            # ------------------------------------
            #
            # Payment is the canonical synchronization point.
            #
            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk
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

            # ------------------------------------
            # Create immutable Refund snapshot
            # ------------------------------------
            #
            # Database constraints remain authoritative.
            #
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
                # ------------------------------------------------------
                # Idempotency race
                # ------------------------------------------------------
                #
                # The unique database constraint is authoritative.
                #
                # Only an existing record with the same idempotency key
                # can turn this expected race into a valid reconciliation.
                #
                existing = (
                    RefundRepository.find_by_idempotency_key_for_update(
                        normalized_key
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

            # ------------------------------------
            # Domain-level financial validation
            # ------------------------------------
            refund.validate_against_payment(
                payment_amount=payment.amount,
                payment_currency=payment.currency,
            )

            # The creation already persisted the immutable snapshot.
            # At this point only request observability may need explicit
            # persistence if callers supplied values that were normalized
            # or modified before creation.
            #
            # Keeping this explicit avoids a generic save() call.
            if ip_address is not None or user_agent or meta:
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
            #
            # IMPORTANT:
            #
            # The Payment lock is intentionally still held here.
            #
            # This preserves V1 cumulative refund concurrency guarantees.
            #
            # An unknown gateway outcome leaves the Refund PENDING and
            # therefore eligible for a later reconciliation workflow.
            #
            try:
                result = GatewayService.refund(
                    payment=payment,
                    refund=refund,
                )

            except PaymentGatewayNotSupportedError:
                # ------------------------------------------------------
                # Deterministic capability failure
                # ------------------------------------------------------
                #
                # The selected gateway explicitly cannot perform refunds.
                # This is not an unknown financial outcome.
                #
                cls._mark_failed(
                    refund=refund,
                    reason="Gateway refund operation is not supported.",
                )
                return refund

            except PaymentGatewayError as exc:
                # ------------------------------------------------------
                # Unknown external outcome
                # ------------------------------------------------------
                #
                # PaymentGatewayError does not prove that the gateway
                # rejected the refund.
                #
                # Example:
                #
                #   gateway accepts refund
                #       ↓
                #   connection drops
                #
                # Marking FAILED here could result in a false financial
                # state and a later duplicate refund.
                #
                cls._register_gateway_exception(
                    refund=refund,
                    exc=exc,
                )
                return refund

            except Exception as exc:
                # ------------------------------------------------------
                # Defensive infrastructure boundary
                # ------------------------------------------------------
                #
                # Any unexpected exception during an external operation
                # has an unknown financial outcome.
                #
                # Keep the Refund PENDING rather than manufacturing a
                # terminal FAILED financial fact.
                #
                cls._register_gateway_exception(
                    refund=refund,
                    exc=exc,
                )
                return refund

            # ------------------------------------
            # Gateway result classification
            # ------------------------------------
            if not result.success:
                cls._mark_failed(
                    refund=refund,
                    reason=cls._gateway_failure_reason(result),
                    response_code=cls._gateway_response_code(result),
                    gateway_message=cls._gateway_message(result),
                )
                return refund

            # ------------------------------------
            # Gateway success must carry trusted identity
            # ------------------------------------
            gateway_reference = cls._normalize_optional(
                result.gateway_reference
            )
            gateway_transaction_id = cls._normalize_optional(
                result.gateway_transaction_id
            )

            if not (
                gateway_reference
                or gateway_transaction_id
            ):
                # A successful external result without a stable gateway
                # identity cannot safely become a terminal financial fact.
                #
                # The gateway result itself claims success, but the Payment
                # Core cannot safely reconcile that success later without
                # an external identity.
                #
                # V1 therefore records this as a deterministic failure of
                # the gateway contract rather than persisting SUCCESS.
                cls._mark_failed(
                    refund=refund,
                    reason=(
                        "Gateway returned success without "
                        "a gateway refund identity."
                    ),
                    response_code=cls._gateway_response_code(result),
                    gateway_message=cls._gateway_message(result),
                )
                return refund

            # ------------------------------------
            # Domain transition: PENDING -> SUCCESS
            # ------------------------------------
            refund.mark_success(
                gateway_reference=gateway_reference,
                gateway_transaction_id=gateway_transaction_id,
                response_code=cls._gateway_response_code(result),
                gateway_message=cls._gateway_message(result),
            )

            RefundRepository.save_success(
                refund
            )

            # ------------------------------------
            # Recalculate cumulative successful refunds
            # ------------------------------------
            #
            # Payment remains locked.
            #
            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk
                )
            )

            cls._validate_successful_refund_total(
                successful_refunded=successful_refunded,
                payment_amount=payment.amount,
            )

            # ------------------------------------
            # Fully refunded Payment
            # ------------------------------------
            #
            # Payment.is_refunded means:
            #
            #     successful_refund_total == payment.amount
            #
            # It does NOT mean that at least one Refund exists.
            #
            if successful_refunded == payment.amount:
                payment.refund()

                PaymentRepository.save_refund_state(
                    payment
                )

            return refund

    # ================================
    # IDEMPOTENCY
    # ================================

    @staticmethod
    def _validate_idempotent_request(
        *,
        refund: Refund,
        payment,
        amount: Decimal,
    ) -> None:
        """
        Validate reuse of an existing idempotency identity.

        Same key is valid only when it represents the same financial
        operation.

        The key is globally unique at the Refund database level, so a key
        associated with another Payment is a conflict rather than a new
        refund request.
        """

        if refund.payment_id != payment.pk:
            raise PaymentInvariantViolation(
                "Refund idempotency key belongs to another Payment."
            )

        if refund.amount != amount:
            raise PaymentRefundAmountInvalidError(
                (
                    "Refund idempotency key was already used with "
                    "a different refund amount."
                )
            )

        if refund.currency != payment.currency:
            raise PaymentCurrencyMismatchError(
                (
                    "Refund idempotency key was already used with "
                    "a different refund currency."
                )
            )

    # ================================
    # FINANCIAL VALIDATION
    # ================================

    @staticmethod
    def _validate_v1_currency(
        currency: str,
    ) -> None:
        """
        Enforce the V1 IRR-only contract.

        Currency conversion, FX and multi-currency arithmetic are
        intentionally outside V1.
        """

        if currency != Currency.IRR:
            raise PaymentCurrencyMismatchError(
                "Only IRR refunds are supported in V1."
            )

    @staticmethod
    def _validate_successful_refund_total(
        *,
        successful_refunded: Decimal,
        payment_amount: Decimal,
    ) -> None:
        """
        Validate the persisted successful-refund aggregate.

        This is an integrity check, not an authorization policy.
        """

        if successful_refunded < Decimal("0"):
            raise PaymentInvariantViolation(
                "Successful refund total cannot be negative."
            )

        if successful_refunded > payment_amount:
            raise PaymentInvariantViolation(
                (
                    "Existing successful refunds already exceed "
                    "the Payment amount."
                )
            )

    @staticmethod
    def _validate_requested_amount(
        *,
        amount: Decimal,
        remaining_refundable: Decimal,
    ) -> None:
        """
        Validate a requested refund against the currently available
        refundable balance.
        """

        if remaining_refundable <= Decimal("0"):
            raise PaymentRefundAmountInvalidError(
                "Payment has no refundable balance remaining."
            )

        if amount > remaining_refundable:
            raise PaymentRefundAmountInvalidError(
                (
                    "Refund amount exceeds the remaining "
                    "refundable balance."
                )
            )

    # ================================
    # GATEWAY EXCEPTION HANDLING
    # ================================

    @staticmethod
    def _register_gateway_exception(
        *,
        refund: Refund,
        exc: Exception,
    ) -> Refund:
        """
        Persist safe evidence for an unknown gateway outcome.

        The exception itself is intentionally not persisted.

        External exceptions may contain:

            - request data
            - credentials
            - URLs
            - provider payloads
            - sensitive information

        GatewayLog/reconciliation infrastructure is the appropriate place
        for technical gateway evidence.

        The Refund lifecycle remains PENDING because the financial outcome
        is unknown.
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
    # TERMINAL FAILURE
    # ================================

    @staticmethod
    def _mark_failed(
        *,
        refund: Refund,
        reason: str,
        response_code: str = "",
        gateway_message: str = "",
    ) -> Refund:
        """
        Persist a deterministic terminal FAILED transition.

        This method must only be used when the application has a
        definitive reason to conclude that the refund did not succeed.

        It must NOT be used for unknown network/transport outcomes.
        """

        if refund.is_terminal:
            return refund

        refund.mark_failed(
            reason=reason,
            response_code=response_code,
            gateway_message=gateway_message,
        )

        RefundRepository.save_failure(
            refund
        )

        return refund

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

    Responsibilities:
        - transaction boundary
        - canonical Payment locking
        - idempotency resolution
        - cumulative refund authorization
        - Refund creation
        - gateway orchestration
        - Refund domain transitions
        - Refund persistence
        - fully-refunded Payment synchronization

    Non-responsibilities:
        - Refund state-machine rules
        - low-level ORM queries
        - repository locking implementation
        - gateway HTTP/protocol implementation
        - provider-specific response parsing
        - Order mutation
        - event publication
        - raw gateway payload persistence

    Concurrency contract:

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

    Payment is the canonical synchronization point for cumulative refund
    authorization.

    Gateway outcome contract:

        definitive rejection
            -> Refund.FAILED

        unknown external outcome
            -> Refund.PENDING

        definitive success + trusted gateway identity
            -> Refund.SUCCESS

    A transport exception is never interpreted as a confirmed gateway
    rejection because the gateway may have accepted the refund before the
    response was lost.
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

        The complete cumulative financial authorization workflow is
        serialized through the Payment row lock.

        The actor parameter is intentionally accepted as application
        context. Refund persistence does not currently own actor identity.
        """

        del actor

        normalized_amount = cls._normalize_amount(amount)
        normalized_key = cls._normalize_idempotency_key(
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
                RefundRepository.find_by_idempotency_key_for_update(
                    normalized_key
                )
            )

            if existing is not None:
                cls._validate_idempotent_request(
                    refund=existing,
                    payment=payment,
                    amount=normalized_amount,
                )
                return existing

            # ------------------------------------
            # Payment eligibility
            # ------------------------------------

            PaymentPolicy.can_refund(payment)

            # ------------------------------------
            # V1 currency contract
            # ------------------------------------

            cls._validate_v1_currency(
                payment.currency
            )

            # ------------------------------------
            # Cumulative successful refund authorization
            # ------------------------------------

            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk
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

            # ------------------------------------
            # Immutable Refund snapshot
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
                The database uniqueness constraint is authoritative.

                An IntegrityError is interpreted as an idempotency race
                only if the idempotency record can actually be resolved.

                Unrelated database integrity failures are re-raised.
                """

                existing = (
                    RefundRepository.find_by_idempotency_key_for_update(
                        normalized_key
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

            # ------------------------------------
            # Domain financial validation
            # ------------------------------------

            refund.validate_against_payment(
                payment_amount=payment.amount,
                payment_currency=payment.currency,
            )

            # ------------------------------------
            # Request observability
            # ------------------------------------

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

            except PaymentGatewayNotSupportedError:
                """
                Capability failure is deterministic.

                The selected gateway explicitly cannot perform refunds,
                therefore this request can safely become FAILED.
                """

                return cls._mark_failed(
                    refund=refund,
                    reason=(
                        "Gateway refund operation is not supported."
                    ),
                )

            except PaymentGatewayError as exc:
                """
                PaymentGatewayError does not necessarily prove rejection.

                GatewayService may raise this for:
                    - timeout
                    - connection failure
                    - provider unavailability
                    - lost response
                    - infrastructure failure

                Therefore the financial outcome remains unknown and the
                Refund stays PENDING for reconciliation.
                """

                return cls._register_gateway_exception(
                    refund=refund,
                    exc=exc,
                )

            except Exception as exc:
                """
                Unknown infrastructure failure.

                Never manufacture a terminal financial failure from an
                exception whose external financial outcome is unknown.
                """

                return cls._register_gateway_exception(
                    refund=refund,
                    exc=exc,
                )

            # ------------------------------------
            # Gateway result validation
            # ------------------------------------

            if not isinstance(
                result,
                GatewayRefundResult,
            ):
                return cls._mark_failed(
                    refund=refund,
                    reason=(
                        "Gateway returned an invalid refund result."
                    ),
                )

            # ------------------------------------
            # Gateway definitive failure
            # ------------------------------------

            if not result.success:
                return cls._mark_failed(
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
                )

            # ------------------------------------
            # Gateway SUCCESS identity
            # ------------------------------------

            gateway_reference = (
                cls._normalize_optional(
                    result.gateway_reference
                )
            )

            gateway_transaction_id = (
                cls._normalize_optional(
                    result.gateway_transaction_id
                )
            )

            if not (
                gateway_reference
                or gateway_transaction_id
            ):
                """
                A success result without an external identity cannot be
                safely reconciled.

                It is intentionally not converted into SUCCESS.

                The provider contract has returned a logically successful
                result, but the Payment Core lacks a trusted external
                identity. This is treated as a deterministic integration
                failure in V1.
                """

                return cls._mark_failed(
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
                )

            # ------------------------------------
            # Domain transition
            # ------------------------------------

            refund.mark_success(
                gateway_reference=gateway_reference,
                gateway_transaction_id=gateway_transaction_id,
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
            # Recalculate authoritative successful total
            # ------------------------------------

            successful_refunded = (
                RefundRepository.successful_amount_for_payment(
                    payment.pk
                )
            )

            cls._validate_successful_refund_total(
                successful_refunded=successful_refunded,
                payment_amount=payment.amount,
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
    # IDEMPOTENCY
    # ================================

    @staticmethod
    def _validate_idempotent_request(
        *,
        refund: Refund,
        payment,
        amount: Decimal,
    ) -> None:
        """
        Validate reuse of an existing idempotency key.

        The same key is valid only for the same Payment financial
        operation.

        The database guarantees global uniqueness of the key. Therefore
        association with another Payment is an application-level conflict.
        """

        if refund.payment_id != payment.pk:
            raise PaymentInvariantViolation(
                "Refund idempotency key belongs to another Payment."
            )

        if refund.amount != amount:
            raise PaymentRefundAmountInvalidError(
                (
                    "Refund idempotency key was already used with "
                    "a different refund amount."
                )
            )

        if refund.currency != payment.currency:
            raise PaymentCurrencyMismatchError(
                (
                    "Refund idempotency key was already used with "
                    "a different refund currency."
                )
            )

    # ================================
    # FINANCIAL VALIDATION
    # ================================

    @staticmethod
    def _validate_v1_currency(
        currency: str,
    ) -> None:
        """
        Enforce the V1 IRR-only financial contract.

        V1 deliberately avoids:
            - FX conversion
            - multi-currency arithmetic
            - fractional currency units
            - exchange-rate snapshots

        These belong to V2 and can be introduced as an extension of the
        existing Payment/Refund contracts rather than a rewrite.
        """

        if currency != Currency.IRR:
            raise PaymentCurrencyMismatchError(
                "Only IRR refunds are supported in V1."
            )

    @staticmethod
    def _validate_successful_refund_total(
        *,
        successful_refunded: Decimal,
        payment_amount: Decimal,
    ) -> None:
        """
        Validate the authoritative persisted successful-refund aggregate.

        This is an integrity assertion, not the refund authorization rule.
        """

        if successful_refunded < Decimal("0"):
            raise PaymentInvariantViolation(
                "Successful refund total cannot be negative."
            )

        if successful_refunded > payment_amount:
            raise PaymentInvariantViolation(
                (
                    "Existing successful refunds already exceed "
                    "the Payment amount."
                )
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
                "Payment has no refundable balance remaining."
            )

        if amount > remaining_refundable:
            raise PaymentRefundAmountInvalidError(
                (
                    "Refund amount exceeds the remaining "
                    "refundable balance."
                )
            )

    # ================================
    # GATEWAY EXCEPTION / UNKNOWN OUTCOME
    # ================================

    @staticmethod
    def _register_gateway_exception(
        *,
        refund: Refund,
        exc: Exception,
    ) -> Refund:
        """
        Preserve safe evidence for an unknown gateway outcome.

        The exception text itself is deliberately not persisted because
        provider exceptions may contain:
            - credentials
            - request payloads
            - URLs
            - headers
            - provider responses
            - sensitive data

        GatewayLog/reconciliation infrastructure remains responsible for
        technical gateway evidence.

        Refund remains PENDING.
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
    # TERMINAL FAILURE
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
        Persist a deterministic terminal FAILED transition.

        This method is intentionally restricted to known failures.

        It must not be used for:
            - timeout
            - connection reset
            - lost response
            - provider unavailability
            - other unknown external outcomes
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
    # GATEWAY RESULT NORMALIZATION
    # ================================

    @staticmethod
    def _gateway_response_code(
        result: GatewayRefundResult,
    ) -> str:
        """
        Return the normalized provider-independent response code.
        """

        return RefundService._normalize_optional(
            result.response_code
        )[:64]

    @staticmethod
    def _gateway_message(
        result: GatewayRefundResult,
    ) -> str:
        """
        Return the normalized provider-independent gateway message.
        """

        return RefundService._normalize_optional(
            result.message
        )[:255]

    @staticmethod
    def _gateway_failure_reason(
        result: GatewayRefundResult,
    ) -> str:
        """
        Build a deterministic, bounded failure reason.

        Raw provider payloads are intentionally excluded.
        """

        message = RefundService._normalize_optional(
            result.message
        )

        if message:
            return message[:255]

        response_code = RefundService._normalize_optional(
            result.response_code
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
        GatewayRefundResult currently does not define latency_ms.

        Keep the service compatible with the existing typed gateway
        contract while allowing a future extended result object to expose
        latency without making V1 depend on it.
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

    # ================================
    # INPUT NORMALIZATION
    # ================================

    @staticmethod
    def _normalize_amount(
        amount: Decimal,
    ) -> Decimal:
        """
        Normalize a financial amount without floating-point arithmetic.
        """

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

        if not normalized.is_finite():
            raise PaymentRefundAmountInvalidError(
                "Refund amount must be finite."
            )

        if normalized <= Decimal("0"):
            raise PaymentRefundAmountInvalidError(
                "Refund amount must be greater than zero."
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
            value or ""
        ).strip()

        if not normalized:
            raise PaymentInvariantViolation(
                "Refund idempotency key is required."
            )

        return normalized

    @staticmethod
    def _normalize_optional(
        value: str | None,
    ) -> str:
        return str(
            value or ""
        ).strip()