# core/payment/exceptions.py
# 
# Payment Core Exceptions
# ================================
#
# Production-grade exception contract for the Payment Core.
#
# Architectural rules
# -------------------
#
# Exceptions in this module:
#
#   - describe failures in the Payment domain/application layer
#   - carry stable machine-readable error codes
#   - may carry safe structured details
#   - must never contain secrets
#   - must not perform persistence
#   - must not perform gateway communication
#   - must not open transactions
#
# Django ValidationError may still be used at the presentation/
# validation boundary, but internal Payment Core workflows should
# progressively migrate to these explicit exceptions.
#
# Layering
# --------
#
# Domain
#   └── PaymentDomainError
#
# Application
#   └── PaymentApplicationError
#
# Persistence / concurrency
#   └── PaymentPersistenceError
#   └── PaymentConcurrencyError
#
# Gateway
#   └── PaymentGatewayError
#
# Security
#   └── PaymentSecurityError
#
# Idempotency
#   └── PaymentIdempotencyError
#
# ================================
from __future__ import annotations

from typing import Any

# ==================================
# Error Codes
# ==================================

class PaymentErrorCode:
    """
    Stable machine-readable error codes.
    These values are part of the application contract.

    They should NOT contain:
        - translated text
        - HTTP status codes
        - gateway-specific response messages
        - database exception strings
        - sensitive information

    Example:
        PAYMENT_NOT_FOUND

    is stable.
        "Payment with id=123 does not exist"

    is not a stable error code.
    """

    # Generic
    UNKNOWN = "payment.unknown"
    INVALID_REQUEST = "payment.invalid_request"

    # Domain
    DOMAIN_ERROR = "payment.domain_error"
    INVARIANT_VIOLATION = "payment.invariant_violation"
    INVALID_STATE = "payment.invalid_state"
    INVALID_TRANSITION = "payment.invalid_transition"

    # Payment
    PAYMENT_NOT_FOUND = "payment.not_found"
    PAYMENT_ALREADY_SUCCESSFUL = "payment.already_successful"
    PAYMENT_ALREADY_FAILED = "payment.already_failed"
    PAYMENT_NOT_PENDING = "payment.not_pending"
    PAYMENT_NOT_REFUNDABLE = "payment.not_refundable"
    PAYMENT_ALREADY_CONSUMED = "payment.already_consumed"
    PAYMENT_ALREADY_REFUNDED = "payment.already_refunded"
    PAYMENT_AMOUNT_MISMATCH = "payment.amount_mismatch"
    PAYMENT_CURRENCY_MISMATCH = "payment.currency_mismatch"
    PAYMENT_GATEWAY_MISMATCH = "payment.gateway_mismatch"

    # Attempt
    ATTEMPT_NOT_FOUND = "payment.attempt.not_found"
    ATTEMPT_NOT_PENDING = "payment.attempt.not_pending"
    ATTEMPT_ALREADY_SUCCESSFUL = "payment.attempt.already_successful"
    ATTEMPT_ALREADY_FAILED = "payment.attempt.already_failed"
    ATTEMPT_ALREADY_FINISHED = "payment.attempt.already_finished"
    ATTEMPT_INVALID_TRANSITION = "payment.attempt.invalid_transition"
    ATTEMPT_IDENTITY_CONFLICT = "payment.attempt.identity_conflict"
    ATTEMPT_NUMBER_CONFLICT = "payment.attempt.number_conflict"
    ATTEMPT_RETRY_INVALID = "payment.attempt.retry_invalid"

    # Policy
    POLICY_VIOLATION = "payment.policy.violation"
    PAYMENT_CREATION_FORBIDDEN = "payment.policy.creation_forbidden"
    PAYMENT_INITIATION_FORBIDDEN = "payment.policy.initiation_forbidden"
    PAYMENT_VERIFICATION_FORBIDDEN = "payment.policy.verification_forbidden"
    PAYMENT_RETRY_FORBIDDEN = "payment.policy.retry_forbidden"
    PAYMENT_REFUND_FORBIDDEN = "payment.policy.refund_forbidden"
    PAYMENT_CONSUMPTION_FORBIDDEN = "payment.policy.consumption_forbidden"

    # Persistence
    PERSISTENCE_ERROR = "payment.persistence.error"
    DUPLICATE_RECORD = "payment.persistence.duplicate"
    RECORD_NOT_FOUND = "payment.persistence.not_found"
    CONSTRAINT_VIOLATION = "payment.persistence.constraint_violation"

    # Concurrency
    CONCURRENCY_CONFLICT = "payment.concurrency.conflict"
    STALE_VERSION = "payment.concurrency.stale_version"
    LOCK_CONFLICT = "payment.concurrency.lock_conflict"

    # Idempotency
    IDEMPOTENCY_CONFLICT = "payment.idempotency.conflict"
    IDEMPOTENCY_KEY_REUSED = "payment.idempotency.key_reused"
    IDEMPOTENT_OPERATION = "payment.idempotency.already_processed"

    # Gateway
    GATEWAY_ERROR = "payment.gateway.error"
    GATEWAY_UNAVAILABLE = "payment.gateway.unavailable"
    GATEWAY_TIMEOUT = "payment.gateway.timeout"
    GATEWAY_INVALID_RESPONSE = "payment.gateway.invalid_response"
    GATEWAY_REJECTED = "payment.gateway.rejected"
    GATEWAY_AUTHENTICATION_FAILED = "payment.gateway.authentication_failed"
    GATEWAY_NOT_SUPPORTED = "payment.gateway.not_supported"
    GATEWAY_IDENTITY_CONFLICT = "payment.gateway.identity_conflict"
    GATEWAY_AMOUNT_MISMATCH = "payment.gateway.amount_mismatch"
    GATEWAY_CURRENCY_MISMATCH = "payment.gateway.currency_mismatch"
    GATEWAY_ALREADY_VERIFIED = "payment.gateway.already_verified"
    GATEWAY_NOT_FOUND = "payment.gateway.not_found"
    GATEWAY_UNKNOWN_RESULT = "payment.gateway.unknown_result"
    
    # Callback / Webhook
    CALLBACK_INVALID = "payment.callback.invalid"
    CALLBACK_MISSING_IDENTITY = "payment.callback.missing_identity"
    CALLBACK_IDENTITY_MISMATCH = "payment.callback.identity_mismatch"
    CALLBACK_REPLAY = "payment.callback.replay"
    CALLBACK_UNAUTHORIZED = "payment.callback.unauthorized"

    # Security
    SECURITY_ERROR = "payment.security.error"
    UNAUTHORIZED = "payment.security.unauthorized"
    FORBIDDEN = "payment.security.forbidden"
    INVALID_SIGNATURE = "payment.security.invalid_signature"
    REPLAY_DETECTED = "payment.security.replay_detected"

    # Refund
    REFUND_ERROR = "payment.refund.error"
    REFUND_NOT_FOUND = "payment.refund.not_found"
    REFUND_NOT_ALLOWED = "payment.refund.not_allowed"
    REFUND_AMOUNT_INVALID = "payment.refund.amount_invalid"

    # Reconciliation
    RECONCILIATION_ERROR = "payment.reconciliation.error"
    RECONCILIATION_REQUIRED = "payment.reconciliation.required"
    RECONCILIATION_UNKNOWN = "payment.reconciliation.unknown"

# ==================================
# Base Exception
# ==================================

class PaymentError(Exception):
    """
    Root exception for the Payment Cor
    All Payment Core-specific exceptions should derive from this class.

    The class intentionally provides:
        code
        message
        details
        retryable

    This gives Application Services a stable error contract without
    coupling them to Django's ValidationError.

    Example:
        raise PaymentError(
            code=PaymentErrorCode.UNKNOWN,
            message="Payment operation failed.",
        )
    """

    code: str = PaymentErrorCode.UNKNOWN
    retryable: bool = False

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.message = message or self.__class__.__name__

        if code is not None:
            self.code = code

        if retryable is not None:
            self.retryable = retryable

        # Details must remain safe application metadata.
        #
        # Do not place:
        #   - passwords
        #   - API keys
        #   - authorization headers
        #   - card data
        #   - raw gateway payloads
        #   - tokens
        #
        # inside details.
        self.details: dict[str, Any] = dict(details or {})
        super().__init__(self.message)
    def __str__(self) -> str:
        return self.message
    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"code={self.code!r} "
            f"retryable={self.retryable!r}>"
        )
    def as_dict(self) -> dict[str, Any]:
        """
        Return a safe machine-readable representation.
        Intended for:
            - logging
            - API exception mapping
            - observability
            - service result translation

        The returned dictionary contains only the exception's
        explicitly supplied safe metadata.
        """

        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
            "retryable": self.retryable,
        }

# ==================================
# Domain Exceptions
# ==================================

class PaymentDomainError(PaymentError):
    """
    Base class for errors caused by invalid Payment domain behavior.
    """
    code = PaymentErrorCode.DOMAIN_ERROR
    retryable = False

class PaymentInvariantViolation(PaymentDomainError):
    """
    Raised when a Payment aggregate invariant is violated.

    Examples:
        amount <= 0
        consumed without success
        refunded without consumption
        terminal state mutation
    """
    code = PaymentErrorCode.INVARIANT_VIOLATION

class PaymentInvalidStateError(PaymentDomainError):
    """
    Raised when an operation is incompatible with the current state.
    """
    code = PaymentErrorCode.INVALID_STATE

class PaymentInvalidTransitionError(PaymentDomainError):
    """
    Raised when an invalid Payment state transition is requested.
    """
    code = PaymentErrorCode.INVALID_TRANSITION

    def __init__(
        self,
        message: str = "Invalid payment state transition.",
        *,
        source_state: str | None = None,
        target_state: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        transition_details = dict(details or {})

        if source_state is not None:
            transition_details["source_state"] = source_state

        if target_state is not None:
            transition_details["target_state"] = target_state

        super().__init__(
            message,
            details=transition_details,
        )

# ==================================
# Payment-Specific Exceptions
# ==================================

class PaymentNotFoundError(PaymentDomainError):
    """
    Payment could not be resolved.
    """
    code = PaymentErrorCode.PAYMENT_NOT_FOUND

class PaymentAlreadySuccessfulError(PaymentDomainError):
    """
    Payment is already financially successful.

    This is useful when the caller expected a new transition but
    the aggregate is already terminal-successful.

    Services may alternatively treat this condition as an
    idempotent success depending on workflow semantics.
    """
    code = PaymentErrorCode.PAYMENT_ALREADY_SUCCESSFUL

class PaymentAlreadyFailedError(PaymentDomainError):
    """
    Payment is already failed.
    """
    code = PaymentErrorCode.PAYMENT_ALREADY_FAILED

class PaymentNotPendingError(PaymentDomainError):
    """
    Operation requires a pending Payment.
    """
    code = PaymentErrorCode.PAYMENT_NOT_PENDING

class PaymentAlreadyConsumedError(PaymentDomainError):
    """
    Payment consumption was requested more than once.
    """
    code = PaymentErrorCode.PAYMENT_ALREADY_CONSUMED

class PaymentAlreadyRefundedError(PaymentDomainError):
    """
    Refund was requested for an already refunded Payment.
    """
    code = PaymentErrorCode.PAYMENT_ALREADY_REFUNDED

class PaymentNotRefundableError(PaymentDomainError):
    """
    Payment does not satisfy refund eligibility rules.
    """

    code = PaymentErrorCode.PAYMENT_NOT_REFUNDABLE

class PaymentAmountMismatchError(PaymentDomainError):
    """
    External/gateway amount does not match the Payment snapshot.
    """
    code = PaymentErrorCode.PAYMENT_AMOUNT_MISMATCH

    def __init__(
        self,
        message: str = "Payment amount does not match.",
        *,
        payment_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_details = dict(details or {})

        if payment_id is not None:
            safe_details["payment_id"] = payment_id

        super().__init__(
            message,
            details=safe_details,
        )

class PaymentCurrencyMismatchError(PaymentDomainError):
    """
    External/gateway currency does not match the Payment snapshot.
    """
    code = PaymentErrorCode.PAYMENT_CURRENCY_MISMATCH

class PaymentGatewayMismatchError(PaymentDomainError):
    """
    Selected gateway does not match the expected gateway.
    """
    code = PaymentErrorCode.PAYMENT_GATEWAY_MISMATCH

# ==================================
# Payment Attempt Exceptions
# ==================================

class PaymentAttemptError(PaymentDomainError):
    """
    Base exception for PaymentAttempt domain failures.
    """
    code = PaymentErrorCode.ATTEMPT_INVALID_TRANSITION

class PaymentAttemptNotFoundError(PaymentAttemptError):
    """
    PaymentAttempt could not be resolved.
    """
    code = PaymentErrorCode.ATTEMPT_NOT_FOUND

class PaymentAttemptNotPendingError(PaymentAttemptError):
    """
    Attempt operation requires a pending attempt.
    """
    code = PaymentErrorCode.ATTEMPT_NOT_PENDING

class PaymentAttemptAlreadySuccessfulError(PaymentAttemptError):
    """
    Attempt has already reached SUCCESS.
    """
    code = PaymentErrorCode.ATTEMPT_ALREADY_SUCCESSFUL

class PaymentAttemptAlreadyFailedError(PaymentAttemptError):
    """
    Attempt has already reached FAILED.
    """
    code = PaymentErrorCode.ATTEMPT_ALREADY_FAILED

class PaymentAttemptAlreadyFinishedError(PaymentAttemptError):
    """
    Attempt has already reached a terminal state.
    """
    code = PaymentErrorCode.ATTEMPT_ALREADY_FINISHED

class PaymentAttemptInvalidTransitionError(
    PaymentAttemptError,
):
    """
    Invalid PaymentAttempt state transition.
    Example:
        SUCCESS -> FAILED
        TIMEOUT -> SUCCESS
        CANCELLED -> SUCCESS
    """
    code = PaymentErrorCode.ATTEMPT_INVALID_TRANSITION

    def __init__(
        self,
        message: str = "Invalid payment attempt state transition.",
        *,
        source_state: str | None = None,
        target_state: str | None = None,
        attempt_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_details = dict(details or {})
        if source_state is not None:
            safe_details["source_state"] = source_state
        if target_state is not None:
            safe_details["target_state"] = target_state
        if attempt_id is not None:
            safe_details["attempt_id"] = attempt_id
        super().__init__(
            message,
            details=safe_details,
        )

class PaymentAttemptIdentityConflictError(
    PaymentAttemptError,
):
    """
    Gateway identity conflict.
    Example:
        stored gateway_reference = A
        incoming gateway_reference = B

    This is NEVER silently overwritten.
    """
    code = PaymentErrorCode.ATTEMPT_IDENTITY_CONFLICT

class PaymentAttemptNumberConflictError(
    PaymentAttemptError,
):
    """
    Attempt number allocation conflict.
    Normally the Payment row lock should prevent this.
    Database uniqueness remains the final safety net.
    """

    code = PaymentErrorCode.ATTEMPT_NUMBER_CONFLICT

class PaymentAttemptRetryError(PaymentAttemptError):
    """
    Invalid retry operation for a PaymentAttempt.
    """
    code = PaymentErrorCode.ATTEMPT_RETRY_INVALID

# ==================================
# Policy Exceptions
# ==================================

class PaymentPolicyError(PaymentDomainError):
    """
    Base class for business-policy violations.

    Policies answer:
        "Is this business operation allowed?"

    They do not perform persistence or orchestration.
    """
    code = PaymentErrorCode.POLICY_VIOLATION

class PaymentCreationForbiddenError(PaymentPolicyError):
    """
    Payment creation is not allowed for the current business state.
    """
    code = PaymentErrorCode.PAYMENT_CREATION_FORBIDDEN

class PaymentInitiationForbiddenError(PaymentPolicyError):
    """
    Payment initiation is not allowed.
    """
    code = PaymentErrorCode.PAYMENT_INITIATION_FORBIDDEN

class PaymentVerificationForbiddenError(PaymentPolicyError):
    """
    Payment verification is not allowed by business policy.
    """
    code = PaymentErrorCode.PAYMENT_VERIFICATION_FORBIDDEN

class PaymentRetryForbiddenError(PaymentPolicyError):
    """
    Payment retry is not allowed.
    """
    code = PaymentErrorCode.PAYMENT_RETRY_FORBIDDEN

class PaymentRefundForbiddenError(PaymentPolicyError):
    """
    Refund is not allowed.
    """
    code = PaymentErrorCode.PAYMENT_REFUND_FORBIDDEN

class PaymentConsumptionForbiddenError(PaymentPolicyError):
    """
    Payment consumption is not allowed.
    """
    code = PaymentErrorCode.PAYMENT_CONSUMPTION_FORBIDDEN

# ==================================
# Persistence Exceptions
# ==================================

class PaymentPersistenceError(PaymentError):
    """
    Base class for persistence-layer failures.
    Repository implementations may translate selected database
    exceptions into these explicit application-level errors.
    IMPORTANT:
    Repositories should NOT blindly catch every database exception.
    Unexpected database failures should normally propagate so
    infrastructure monitoring can detect them.
    """
    code = PaymentErrorCode.PERSISTENCE_ERROR
    retryable = False

class PaymentDuplicateRecordError(PaymentPersistenceError):
    """
    A database uniqueness constraint was violated.
    """
    code = PaymentErrorCode.DUPLICATE_RECORD

class PaymentRecordNotFoundError(PaymentPersistenceError):
    """
    Persistence-layer lookup failed because the record does not exist.
    """
    code = PaymentErrorCode.RECORD_NOT_FOUND

class PaymentConstraintViolationError(PaymentPersistenceError):
    """
    Database structural constraint was violated.
    """
    code = PaymentErrorCode.CONSTRAINT_VIOLATION

# ==================================
# Concurrency Exceptions
# ==================================

class PaymentConcurrencyError(PaymentError):
    """
    Base class for Payment concurrency failures.

    Typical causes:
        - stale version
        - optimistic lock failure
        - incompatible concurrent mutation
        - lock acquisition conflict

    A concurrency failure is usually retryable at the application
    workflow level, but the workflow must determine whether retrying
    the entire operation is safe.
    """
    code = PaymentErrorCode.CONCURRENCY_CONFLICT
    retryable = True

class PaymentStaleVersionError(PaymentConcurrencyError):
    """
    Optimistic concurrency check failed.

    Example:
        expected version = 4
        database version = 5
    """
    code = PaymentErrorCode.STALE_VERSION

class PaymentLockConflictError(PaymentConcurrencyError):
    """
    A required persistence lock could not be acquired safely.
    """
    code = PaymentErrorCode.LOCK_CONFLICT

# ==================================
# Idempotency Exceptions
# ==================================

class PaymentIdempotencyError(PaymentError):
    """
    Base class for idempotency-related failures.
    """
    code = PaymentErrorCode.IDEMPOTENCY_CONFLICT

class PaymentIdempotencyConflictError(
    PaymentIdempotencyError,
):
    """
    Same idempotency identity was used for semantically different
    operations.

    Example:
        idempotency_key = abc

        first request:
            payment=10
            operation=verify

        second request:
            payment=11
            operation=verify

    The second operation must not silently reuse the first result.
    """
    code = PaymentErrorCode.IDEMPOTENCY_CONFLICT

class PaymentIdempotencyKeyReuseError(
    PaymentIdempotencyError,
):
    """
    An idempotency key was reused in an incompatible context.
    """
    code = PaymentErrorCode.IDEMPOTENCY_KEY_REUSED

class PaymentAlreadyProcessedError(
    PaymentIdempotencyError,
):
    """
    Operation has already been processed.
    Depending on the service contract, this may be converted into
    an idempotent success result rather than surfaced as an error.
    """
    code = PaymentErrorCode.IDEMPOTENT_OPERATION
    
# ==================================
# Gateway Exceptions
# ==================================

class PaymentGatewayError(PaymentError):
    """
    Base exception for gateway adapter failures.
    Gateway exceptions represent communication/integration problems.
    They MUST NOT mutate Payment or PaymentAttempt directly.
    """
    code = PaymentErrorCode.GATEWAY_ERROR
    retryable = False

class PaymentGatewayUnavailableError(
    PaymentGatewayError,
):
    """
    Gateway is temporarily unavailable.
    Usually retryable.
    """
    code = PaymentErrorCode.GATEWAY_UNAVAILABLE
    retryable = True

class PaymentGatewayTimeoutError(
    PaymentGatewayError,
):
    """
    Gateway communication timed out.
    CRITICAL:
        Timeout != financial failure.
    A timeout means the application did not obtain a definitive
    response. The gateway may still have processed the transaction.
    Therefore this exception should normally lead to reconciliation,
    not immediate financial failure.
    """
    code = PaymentErrorCode.GATEWAY_TIMEOUT
    retryable = True

class PaymentGatewayInvalidResponseError(
    PaymentGatewayError,
):
    """
    Gateway returned a response that could not be safely normalized.
    """
    code = PaymentErrorCode.GATEWAY_INVALID_RESPONSE

class PaymentGatewayRejectedError(
    PaymentGatewayError,
):
    """
    Gateway explicitly rejected the operation.
    """
    code = PaymentErrorCode.GATEWAY_REJECTED

class PaymentGatewayAuthenticationError(
    PaymentGatewayError,
):
    """
    Gateway authentication/configuration failed.
    Usually NOT safe to blindly retry immediately.
    """
    code = PaymentErrorCode.GATEWAY_AUTHENTICATION_FAILED

class PaymentGatewayNotSupportedError(
    PaymentGatewayError,
):
    """
    Requested gateway capability is not supported.
    """
    code = PaymentErrorCode.GATEWAY_NOT_SUPPORTED

class PaymentGatewayIdentityConflictError(
    PaymentGatewayError,
):
    """
    Gateway response contains an identity that conflicts with
    the application's expected PaymentAttempt identity.
    """
    code = PaymentErrorCode.GATEWAY_IDENTITY_CONFLICT

class PaymentGatewayAmountMismatchError(
    PaymentGatewayError,
):
    """
    Gateway-reported amount differs from the Payment financial snapshot.
    This is a financial integrity failure, not a transport failure.
    """
    code = PaymentErrorCode.GATEWAY_AMOUNT_MISMATCH

class PaymentGatewayCurrencyMismatchError(
    PaymentGatewayError,
):
    """
    Gateway-reported currency differs from the Payment currency.
    """
    code = PaymentErrorCode.GATEWAY_CURRENCY_MISMATCH

class PaymentGatewayAlreadyVerifiedError(
    PaymentGatewayError,
):
    """
    Gateway indicates that the transaction was already verified.
    Application Services may translate this into an idempotent
    successful verification depending on gateway semantics.
    """
    code = PaymentErrorCode.GATEWAY_ALREADY_VERIFIED

class PaymentGatewayNotFoundError(
    PaymentGatewayError,
):
    """
    Gateway cannot find the requested transaction/authority.
    """
    code = PaymentErrorCode.GATEWAY_NOT_FOUND

class PaymentGatewayUnknownResultError(
    PaymentGatewayError,
):
    """
    Gateway result cannot safely be classified as success/failure.
    This is intentionally distinct from an explicit rejection.
    Reconciliation may be required.
    """

    code = PaymentErrorCode.GATEWAY_UNKNOWN_RESULT

# ==================================
# Callback / Webhook Exceptions
# ==================================

class PaymentCallbackError(PaymentError):
    """
    Base callback processing error.
    """
    code = PaymentErrorCode.CALLBACK_INVALID

class PaymentInvalidCallbackError(
    PaymentCallbackError,
):
    """
    Callback payload is structurally invalid.
    """
    code = PaymentErrorCode.CALLBACK_INVALID

class PaymentCallbackMissingIdentityError(
    PaymentCallbackError,
):
    """
    Callback does not contain enough trusted identity information
    to safely resolve the PaymentAttempt.
    """
    code = PaymentErrorCode.CALLBACK_MISSING_IDENTITY

class PaymentCallbackIdentityMismatchError(
    PaymentCallbackError,
):
    """
    Callback identity conflicts with stored PaymentAttempt identity.
    """
    code = PaymentErrorCode.CALLBACK_IDENTITY_MISMATCH

class PaymentCallbackReplayError(
    PaymentCallbackError,
):
    """
    Callback was identified as a replay.
    Note:
    A replay may still be harmless and idempotent.
    The Service layer decides whether this becomes:
        - ignored
        - idempotent success
        - explicit rejection
    """
    code = PaymentErrorCode.CALLBACK_REPLAY

class PaymentCallbackUnauthorizedError(
    PaymentCallbackError,
):
    """
    Callback failed authentication/authorization checks.
    """
    code = PaymentErrorCode.CALLBACK_UNAUTHORIZED

# ==================================
# Security Exceptions
# ==================================

class PaymentSecurityError(PaymentError):
    """
    Base Payment security exception.
    """
    code = PaymentErrorCode.SECURITY_ERROR

class PaymentUnauthorizedError(
    PaymentSecurityError,
):
    """
    Caller is not authenticated/authorized for the operation.
    """
    code = PaymentErrorCode.UNAUTHORIZED

class PaymentForbiddenError(
    PaymentSecurityError,
):
    """
    Caller is authenticated but not permitted to perform the
    requested operation.
    """
    code = PaymentErrorCode.FORBIDDEN

class PaymentInvalidSignatureError(
    PaymentSecurityError,
):
    """
    Gateway callback/webhook signature is invalid.
    """
    code = PaymentErrorCode.INVALID_SIGNATURE

class PaymentReplayDetectedError(
    PaymentSecurityError,
):
    """
    Security layer detected a replay attack.
    """
    code = PaymentErrorCode.REPLAY_DETECTED

# ==================================
# Refund Exceptions
# ==================================

class PaymentRefundError(PaymentError):
    """
    Base refund exception.
    """
    code = PaymentErrorCode.REFUND_ERROR

class PaymentRefundNotFoundError(
    PaymentRefundError,
):
    """
    Requested Refund does not exist.
    """
    code = PaymentErrorCode.REFUND_NOT_FOUND

class PaymentRefundNotAllowedError(
    PaymentRefundError,
):
    """
    Refund operation violates refund policy.
    """
    code = PaymentErrorCode.REFUND_NOT_ALLOWED

class PaymentRefundAmountInvalidError(
    PaymentRefundError,
):
    """
    Refund amount is invalid.
    """
    code = PaymentErrorCode.REFUND_AMOUNT_INVALID

# ==================================
# Reconciliation Exceptions
# ==================================

class PaymentReconciliationError(PaymentError):
    """
    Base reconciliation exception.
    """
    code = PaymentErrorCode.RECONCILIATION_ERROR

class PaymentReconciliationRequiredError(
    PaymentReconciliationError,
):
    """
    Payment state cannot safely be finalized without reconciliation.
    """
    code = PaymentErrorCode.RECONCILIATION_REQUIRED
    retryable = True

class PaymentReconciliationUnknownError(
    PaymentReconciliationError,
):
    """
    Gateway inquiry returned an indeterminate result.

    IMPORTANT:
    UNKNOWN must remain recoverable.
    It must never be silently converted to FAILED.
    """

    code = PaymentErrorCode.RECONCILIATION_UNKNOWN
    retryable = True