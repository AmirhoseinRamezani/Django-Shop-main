# core/payment/policies.py
# ================================
# Payment Business Policies
# ================================
# Production-grade business decision layer for Payment Core.
# ARCHITECTURAL CONTRACT
# ----------------------
#
# Policies answer one question:
#     "Is this business operation allowed?"
#
# Policies MUST:
#   - contain business decisions only
#   - be deterministic
#   - be side-effect free
#   - avoid persistence
#   - avoid repository access
#   - avoid database transactions
#   - avoid gateway communication
#   - avoid HTTP
#   - avoid event dispatch
#   - avoid Celery/task dispatch
#   - avoid mutating Payment
#   - avoid mutating PaymentAttempt
#   - avoid mutating Order
#
# Policies MAY:
#   - inspect already-loaded domain objects
#   - inspect domain state
#   - validate business preconditions
#   - raise Payment Core exceptions
#   - return boolean decisions
#
# APPLICATION SERVICES
# --------------------
#
# Application Services are responsible for orchestration:
#   - repositories
#   - transactions
#   - locking
#   - gateway calls
#   - attempt creation
#   - persistence
#   - event dispatch
#   - idempotency storage
#   - reconciliation workflows
#
# DOMAIN MODELS
# -------------
#
# Models are responsible for aggregate-local invariants and
# state mutation through their domain commands.
#
# Example:
#     PaymentPolicy.can_succeed(payment)
#     payment.succeed()
#
# The Policy decides whether the operation is allowed.
# The Model performs the domain state mutation.
#
# ================================

from __future__ import annotations

from order.models import OrderStatusType
from payment.enums import (
    PaymentAttemptStatus,
    PaymentStatusType,
)
from payment.exceptions import (
    PaymentAlreadyConsumedError,
    PaymentAlreadyFailedError,
    PaymentAlreadyRefundedError,
    PaymentAlreadySuccessfulError,
    PaymentAttemptAlreadyFailedError,
    PaymentAttemptAlreadyFinishedError,
    PaymentAttemptAlreadySuccessfulError,
    PaymentAttemptInvalidTransitionError,
    PaymentAttemptNotPendingError,
    PaymentAttemptRetryError,
    PaymentConsumptionForbiddenError,
    PaymentCreationForbiddenError,
    PaymentInvalidStateError,
    PaymentInitiationForbiddenError,
    PaymentNotPendingError,
    PaymentNotRefundableError,
    PaymentPolicyError,
    PaymentRefundForbiddenError,
    PaymentRetryForbiddenError,
    PaymentVerificationForbiddenError,
)

# ====================================
# Payment Policy
# ====================================
class PaymentPolicy:
    """
    Authoritative business policy for Payment workflows.
    This class contains decisions only.

    It does NOT:
        - query repositories
        - access the database
        - open transactions
        - acquire locks
        - call gateways
        - persist models
        - mutate Payment
        - mutate PaymentAttempt
        - mutate Order
        - dispatch events
        - dispatch tasks
        - perform HTTP requests

    The policy operates only on already-loaded domain objects.
    Application Services are responsible for orchestration.
    """
    # ====================================
    # Payment Creation
    # ====================================
    @staticmethod
    def can_create_payment(order) -> bool:
        """
        Determine whether a new Payment may be created for an Order.

        Business rules
        --------------

        Allowed:
            Order exists
            Order is pending
            Order is not expired

        Not checked here:
            Existing payments
            Existing pending attempts
            Duplicate payment detection
            Repository state
            Database constraints

        Those concerns belong to the Application Service /
        Repository layer.

        Returns
        -------
        True
            Payment creation is allowed.
        Raises
        ------
        PaymentCreationForbiddenError
            Order state does not allow payment creation.
        """

        if order is None:
            raise PaymentCreationForbiddenError(
                "Order is required."
            )

        if order.status != OrderStatusType.pending:
            raise PaymentCreationForbiddenError(
                "Payment is not allowed for the current order state.",
                details={
                    "order_status": str(order.status),
                },
            )

        if order.is_expired():
            raise PaymentCreationForbiddenError(
                "Payment is not allowed for an expired order."
            )

        return True

    # ====================================
    # Payment Initiation
    # ====================================

    @staticmethod
    def can_initiate(payment) -> bool:
        """
        Determine whether a Payment may begin a gateway execution cycle.

        Allowed:

            PENDING -> initiation

        Forbidden:

            SUCCESS
            FAILED

        Important:

            This method does NOT determine whether another pending
            PaymentAttempt already exists.

            That is a repository/application-service concern.
        """

        if payment is None:
            raise PaymentInitiationForbiddenError(
                "Payment is required."
            )

        if payment.status != PaymentStatusType.PENDING:
            raise PaymentInitiationForbiddenError(
                "Only pending payments can be initiated.",
                details={
                    "payment_status": str(payment.status),
                },
            )

        return True

    # ====================================
    # Payment Verification
    # ====================================

    @staticmethod
    def can_verify(payment) -> bool:
        """
        Determine whether Payment verification may perform a new
        financial state transition.

        Semantics:

            PENDING
                -> verification is allowed.

            SUCCESS
                -> no new financial transition is required.
                   The Application Service may treat this as an
                   idempotent successful result.

            FAILED
                -> verification is forbidden.

        Returns
        -------

        True
            A verification workflow may proceed.

        False
            Payment is already successfully finalized and the
            operation should be handled idempotently.

        Raises
        ------

        PaymentVerificationForbiddenError
            Verification is impossible for the current state.
        """

        if payment is None:
            raise PaymentVerificationForbiddenError(
                "Payment is required."
            )

        if payment.status == PaymentStatusType.SUCCESS:
            return False

        if payment.status != PaymentStatusType.PENDING:
            raise PaymentVerificationForbiddenError(
                "This payment cannot be verified.",
                details={
                    "payment_status": str(payment.status),
                },
            )

        return True

    # ====================================
    # Payment Retry
    # ====================================

    @staticmethod
    def can_retry(payment) -> bool:
        """
        Determine whether a Payment may start another execution attempt.

        Current Payment state machine:

            PENDING -> SUCCESS
            PENDING -> FAILED

        SUCCESS and FAILED are terminal.

        Therefore:

            PENDING
                -> retry may be represented by a NEW PaymentAttempt.

            SUCCESS
                -> retry forbidden.

            FAILED
                -> retry forbidden.

        IMPORTANT:

        Retry MUST NOT mutate:

            FAILED -> PENDING

        and MUST NOT mutate:

            SUCCESS -> PENDING

        A retry is represented by a new PaymentAttempt while the
        Payment aggregate remains within its valid lifecycle.

        Whether a new attempt is actually created is an
        Application Service responsibility.
        """

        if payment is None:
            raise PaymentRetryForbiddenError(
                "Payment is required."
            )

        if payment.status != PaymentStatusType.PENDING:
            raise PaymentRetryForbiddenError(
                "A terminal payment cannot be retried.",
                details={
                    "payment_status": str(payment.status),
                },
            )

        return True

    # ====================================
    # Payment Consumption
    # ====================================

    @staticmethod
    def can_consume(payment) -> bool:
        """
        Determine whether a successful Payment may be consumed.

        Business rule:

            SUCCESS
                +
            is_consumed == False
                ->
            consumable

        Consumption is exactly-once from the business perspective.

        The actual atomic persistence operation belongs to the
        Application Service / Repository layer.
        """

        if payment is None:
            raise PaymentConsumptionForbiddenError(
                "Payment is required."
            )

        if payment.status != PaymentStatusType.SUCCESS:
            raise PaymentConsumptionForbiddenError(
                "Only successful payments can be consumed.",
                details={
                    "payment_status": str(payment.status),
                },
            )

        if payment.is_consumed:
            raise PaymentAlreadyConsumedError(
                "Payment has already been consumed."
            )

        return True

    # ====================================
    # Refund
    # ====================================

    @staticmethod
    def can_refund(payment) -> bool:
        """
        Determine whether a Payment satisfies the current refund policy.

        Current business rule:

            Payment SUCCESS
                +
            Payment CONSUMED
                +
            Payment NOT REFUNDED

        IMPORTANT:

        This policy only decides refund eligibility.

        It does NOT execute the gateway refund.

        Gateway refund execution belongs to RefundService / gateway
        adapter infrastructure.

        The Payment aggregate may later record the successful
        refund using its domain command.
        """

        if payment is None:
            raise PaymentRefundForbiddenError(
                "Payment is required."
            )

        if payment.status != PaymentStatusType.SUCCESS:
            raise PaymentRefundForbiddenError(
                "Only successful payments can be refunded.",
                details={
                    "payment_status": str(payment.status),
                },
            )

        if not payment.is_consumed:
            raise PaymentRefundForbiddenError(
                "A consumed payment is required before refund."
            )

        if payment.is_refunded:
            raise PaymentAlreadyRefundedError(
                "Payment has already been refunded."
            )

        return True

    # ====================================
    # Payment -> SUCCESS
    # ====================================

    @staticmethod
    def can_succeed(payment) -> bool:
        """
        Determine whether Payment may transition to SUCCESS.

        State machine:

            PENDING -> SUCCESS
                allowed

            SUCCESS -> SUCCESS
                idempotent

            FAILED -> SUCCESS
                forbidden

        This policy does not perform the transition.

        The domain aggregate performs it through:

            payment.succeed()
        """

        if payment is None:
            raise PaymentInvalidStateError(
                "Payment is required."
            )

        if payment.status == PaymentStatusType.SUCCESS:
            return True

        if payment.status == PaymentStatusType.FAILED:
            raise PaymentAlreadyFailedError(
                "A failed payment cannot transition to successful."
            )

        if payment.status != PaymentStatusType.PENDING:
            raise PaymentInvalidStateError(
                "Only pending payments can transition to successful.",
                details={
                    "payment_status": str(payment.status),
                },
            )

        return True

    # ====================================
    # Payment -> FAILED
    # ====================================

    @staticmethod
    def can_fail(payment) -> bool:
        """
        Determine whether Payment may transition to FAILED.

        State machine:

            PENDING -> FAILED
                allowed

            FAILED -> FAILED
                idempotent

            SUCCESS -> FAILED
                forbidden

        This policy does not mutate the aggregate.
        """

        if payment is None:
            raise PaymentInvalidStateError(
                "Payment is required."
            )

        if payment.status == PaymentStatusType.FAILED:
            return True

        if payment.status == PaymentStatusType.SUCCESS:
            raise PaymentAlreadySuccessfulError(
                "A successful payment cannot transition to failed."
            )

        if payment.status != PaymentStatusType.PENDING:
            raise PaymentInvalidStateError(
                "Only pending payments can transition to failed.",
                details={
                    "payment_status": str(payment.status),
                },
            )

        return True


# ====================================
# Payment Attempt Policy
# ====================================


class PaymentAttemptPolicy:
    """
    Authoritative business policy for PaymentAttempt workflows.

    PaymentAttempt represents one gateway execution cycle.

    This policy deals exclusively with Attempt-level decisions.

    It does NOT:
        - mutate Payment
        - mutate PaymentAttempt
        - create PaymentAttempt
        - calculate attempt numbers
        - query PaymentAttempt records
        - acquire database locks
        - call gateways
        - persist models
        - dispatch events
        - perform reconciliation
        - perform HTTP
    """

    # ====================================
    # Start
    # ====================================

    @staticmethod
    def can_start(attempt) -> bool:
        """
        Determine whether an Attempt may be started.

        Only PENDING represents an active execution cycle.

        A terminal Attempt is historical and cannot be restarted.

        Returns
        -------

        True
            Attempt can be started.

        Raises
        ------

        PaymentAttemptNotPendingError
            Attempt is not pending.
        """

        if attempt is None:
            raise PaymentAttemptNotPendingError(
                "Payment attempt is required."
            )

        if attempt.status != PaymentAttemptStatus.PENDING:
            raise PaymentAttemptNotPendingError(
                "Only pending payment attempts can be started.",
                details={
                    "attempt_status": str(attempt.status),
                },
            )

        return True

    # ====================================
    # Attempt -> SUCCESS
    # ====================================

    @staticmethod
    def can_succeed(attempt) -> bool:
        """
        Determine whether an Attempt may transition to SUCCESS.

        State machine:

            PENDING -> SUCCESS
                allowed

            SUCCESS -> SUCCESS
                idempotent

            FAILED -> SUCCESS
                forbidden

            TIMEOUT -> SUCCESS
                forbidden

            CANCELLED -> SUCCESS
                forbidden

        IMPORTANT:

        TIMEOUT is not financial SUCCESS.

        A later gateway inquiry/reconciliation may discover that
        the gateway actually succeeded, but that workflow must
        not mutate the historical TIMEOUT Attempt back to SUCCESS.

        Instead, the Application Service must reconcile the
        Payment aggregate using a valid workflow.
        """

        if attempt is None:
            raise PaymentAttemptInvalidTransitionError(
                "Payment attempt is required."
            )

        if attempt.status == PaymentAttemptStatus.SUCCESS:
            return True

        if attempt.status == PaymentAttemptStatus.FAILED:
            raise PaymentAttemptInvalidTransitionError(
                "A failed payment attempt cannot transition to successful.",
                source_state=PaymentAttemptStatus.FAILED,
                target_state=PaymentAttemptStatus.SUCCESS,
                attempt_id=getattr(attempt, "pk", None),
            )

        if attempt.status == PaymentAttemptStatus.TIMEOUT:
            raise PaymentAttemptInvalidTransitionError(
                "A timed-out payment attempt cannot transition to successful.",
                source_state=PaymentAttemptStatus.TIMEOUT,
                target_state=PaymentAttemptStatus.SUCCESS,
                attempt_id=getattr(attempt, "pk", None),
            )

        if attempt.status == PaymentAttemptStatus.CANCELLED:
            raise PaymentAttemptInvalidTransitionError(
                "A cancelled payment attempt cannot transition to successful.",
                source_state=PaymentAttemptStatus.CANCELLED,
                target_state=PaymentAttemptStatus.SUCCESS,
                attempt_id=getattr(attempt, "pk", None),
            )

        if attempt.status != PaymentAttemptStatus.PENDING:
            raise PaymentAttemptInvalidTransitionError(
                "Only pending payment attempts can transition to successful.",
                source_state=str(attempt.status),
                target_state=PaymentAttemptStatus.SUCCESS,
                attempt_id=getattr(attempt, "pk", None),
            )

        return True

    # ====================================
    # Attempt -> FAILED
    # ====================================

    @staticmethod
    def can_fail(attempt) -> bool:
        """
        Determine whether an Attempt may transition to FAILED.

        Allowed:

            PENDING -> FAILED

        Idempotent:

            FAILED -> FAILED

        Forbidden:

            SUCCESS -> FAILED
            TIMEOUT -> FAILED
            CANCELLED -> FAILED
        """

        if attempt is None:
            raise PaymentAttemptInvalidTransitionError(
                "Payment attempt is required."
            )

        if attempt.status == PaymentAttemptStatus.FAILED:
            return True

        if attempt.status == PaymentAttemptStatus.SUCCESS:
            raise PaymentAttemptAlreadySuccessfulError(
                "A successful payment attempt cannot transition to failed."
            )

        if attempt.status in {
            PaymentAttemptStatus.TIMEOUT,
            PaymentAttemptStatus.CANCELLED,
        }:
            raise PaymentAttemptAlreadyFinishedError(
                "A finished payment attempt cannot transition to failed.",
                details={
                    "attempt_status": str(attempt.status),
                },
            )

        if attempt.status != PaymentAttemptStatus.PENDING:
            raise PaymentAttemptInvalidTransitionError(
                "Only pending payment attempts can transition to failed.",
                source_state=str(attempt.status),
                target_state=PaymentAttemptStatus.FAILED,
                attempt_id=getattr(attempt, "pk", None),
            )

        return True

    # ====================================
    # Attempt -> TIMEOUT
    # ====================================

    @staticmethod
    def can_timeout(attempt) -> bool:
        """
        Determine whether an Attempt may transition to TIMEOUT.

        Allowed:

            PENDING -> TIMEOUT

        Idempotent:

            TIMEOUT -> TIMEOUT

        Forbidden:

            SUCCESS -> TIMEOUT
            FAILED -> TIMEOUT
            CANCELLED -> TIMEOUT

        IMPORTANT:

        TIMEOUT is a technical execution state.

        It MUST NOT automatically become:

            Payment FAILED

        because the gateway may have processed the transaction
        despite the local timeout.

        Such uncertainty belongs to reconciliation.
        """

        if attempt is None:
            raise PaymentAttemptInvalidTransitionError(
                "Payment attempt is required."
            )

        if attempt.status == PaymentAttemptStatus.TIMEOUT:
            return True

        if attempt.status == PaymentAttemptStatus.SUCCESS:
            raise PaymentAttemptAlreadySuccessfulError(
                "A successful payment attempt cannot transition to timeout."
            )

        if attempt.status in {
            PaymentAttemptStatus.FAILED,
            PaymentAttemptStatus.CANCELLED,
        }:
            raise PaymentAttemptAlreadyFinishedError(
                "A finished payment attempt cannot transition to timeout.",
                details={
                    "attempt_status": str(attempt.status),
                },
            )

        if attempt.status != PaymentAttemptStatus.PENDING:
            raise PaymentAttemptInvalidTransitionError(
                "Only pending payment attempts can transition to timeout.",
                source_state=str(attempt.status),
                target_state=PaymentAttemptStatus.TIMEOUT,
                attempt_id=getattr(attempt, "pk", None),
            )

        return True

    # ====================================
    # Attempt -> CANCELLED
    # ====================================

    @staticmethod
    def can_cancel(attempt) -> bool:
        """
        Determine whether an Attempt may transition to CANCELLED.

        Allowed:

            PENDING -> CANCELLED

        Idempotent:

            CANCELLED -> CANCELLED

        Forbidden:

            SUCCESS -> CANCELLED
            FAILED -> CANCELLED
            TIMEOUT -> CANCELLED
        """

        if attempt is None:
            raise PaymentAttemptInvalidTransitionError(
                "Payment attempt is required."
            )

        if attempt.status == PaymentAttemptStatus.CANCELLED:
            return True

        if attempt.status == PaymentAttemptStatus.SUCCESS:
            raise PaymentAttemptAlreadySuccessfulError(
                "A successful payment attempt cannot be cancelled."
            )

        if attempt.status in {
            PaymentAttemptStatus.FAILED,
            PaymentAttemptStatus.TIMEOUT,
        }:
            raise PaymentAttemptAlreadyFinishedError(
                "A finished payment attempt cannot be cancelled.",
                details={
                    "attempt_status": str(attempt.status),
                },
            )

        if attempt.status != PaymentAttemptStatus.PENDING:
            raise PaymentAttemptInvalidTransitionError(
                "Only pending payment attempts can be cancelled.",
                source_state=str(attempt.status),
                target_state=PaymentAttemptStatus.CANCELLED,
                attempt_id=getattr(attempt, "pk", None),
            )

        return True

    # ====================================
    # Callback / Webhook
    # ====================================

    @staticmethod
    def can_receive_callback(attempt) -> bool:
        """
        Determine whether a callback may enter the callback-processing
        workflow.

        IMPORTANT:

        Terminal state alone does NOT make a callback invalid.

        Examples:

            SUCCESS + duplicate callback
                -> potentially idempotent

            TIMEOUT + late callback
                -> reconciliation candidate

            FAILED + late callback
                -> identity/reconciliation workflow

            CANCELLED + late callback
                -> security/reconciliation workflow

        Therefore this policy intentionally does not reject terminal
        attempts.

        The callback Application Service is responsible for:

            - validating callback authenticity
            - resolving trusted identity
            - checking authority/reference
            - validating gateway
            - validating amount/currency
            - detecting replay
            - determining idempotency
            - deciding whether reconciliation is required

        This policy only confirms that callback processing itself
        is not prohibited merely because the Attempt is terminal.
        """

        if attempt is None:
            raise PaymentInvalidStateError(
                "Payment attempt is required."
            )

        return True

    # ====================================
    # Retry
    # ====================================

    @staticmethod
    def can_retry(attempt) -> bool:
        """
        Determine whether an existing Attempt may serve as the
        historical parent of a new retry Attempt.

        Rules:

            PENDING
                -> forbidden

            SUCCESS
                -> retry may be considered by the application
                   workflow, but a successful financial Payment
                   must never be retried as a way to charge again.

            FAILED
                -> retry candidate

            TIMEOUT
                -> retry candidate only through an application
                   workflow that understands the financial uncertainty

            CANCELLED
                -> retry candidate

        IMPORTANT:

        This method does NOT create the retry.

        The Application Service must:

            1. resolve the Payment
            2. enforce the Payment-level retry policy
            3. acquire the required locks
            4. allocate a new attempt_number
            5. create a NEW PaymentAttempt
            6. set retry_of
            7. persist atomically

        The historical Attempt must never be mutated back to PENDING.
        """

        if attempt is None:
            raise PaymentAttemptRetryError(
                "Payment attempt is required."
            )

        if attempt.status == PaymentAttemptStatus.PENDING:
            raise PaymentAttemptNotPendingError(
                "A pending payment attempt cannot be retried "
                "until its current execution is resolved."
            )

        if attempt.status == PaymentAttemptStatus.SUCCESS:
            raise PaymentAttemptRetryError(
                "A successful payment attempt cannot be retried "
                "as a new charge cycle."
            )

        if attempt.status not in {
            PaymentAttemptStatus.FAILED,
            PaymentAttemptStatus.TIMEOUT,
            PaymentAttemptStatus.CANCELLED,
        }:
            raise PaymentAttemptRetryError(
                "This payment attempt cannot be used as a retry parent.",
                details={
                    "attempt_status": str(attempt.status),
                },
            )

        return True