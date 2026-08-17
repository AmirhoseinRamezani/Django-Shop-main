# core/payment/managers.py
# ===============================
# Payment Query / Manager Layer
# Architectural Contract
# ----------------------
#
# Managers and QuerySets are persistence/query composition tools.
#
# They MAY:
#   - filter
#   - order
#   - select_related
#   - prefetch_related
#   - select_for_update
#   - select_for_update(skip_locked=True)
#
# They MUST NOT:
#   - decide business eligibility
#   - perform payment workflows
#   - call gateways
#   - verify payments
#   - initiate payments
#   - retry payments
#   - process callbacks
#   - refund payments
#   - mutate Payment / Order state
#   - open transaction.atomic()
#
# Business decisions belong to:
#     payment/policies.py
#
# Workflow orchestration belongs to:
#     payment/services/
#
# Persistence boundaries belong to:
#     payment/repositories/
# ================================

from __future__ import annotations

from django.db import models

from payment.enums import (
    GatewayLogDirection,
    GatewayLogType,
    PaymentAttemptStatus,
    PaymentStatusType,
    RefundStatus,
)

# ================================
# Payment QuerySet
# ================================

class PaymentQuerySet(models.QuerySet):
    """
    Query composition API for PaymentModel.
    This class contains persistence-level predicates only.
    
    No method in this QuerySet should answer questions such as:
        can this payment be paid?
        can this payment be retried?
        can this payment be refunded?

    Those are domain/application policy questions.
    """

    # ------------------------
    # State Queries
    # ------------------------

    def pending(self) -> "PaymentQuerySet":
        """
        Return payments currently in PENDING state.
        """
        return self.filter(
            status=PaymentStatusType.PENDING,
        )

    def successful(self) -> "PaymentQuerySet":
        """
        Return payments currently in SUCCESS state.
        """
        return self.filter(
            status=PaymentStatusType.SUCCESS,
        )

    def failed(self) -> "PaymentQuerySet":
        """
        Return payments currently in FAILED state.
        """
        return self.filter(
            status=PaymentStatusType.FAILED,
        )

    # ------------------------
    # Consumption / Refund State
    # ------------------------

    def consumed(self) -> "PaymentQuerySet":
        """
        Return payments that have been consumed.
        This is intentionally a simple persistence predicate.
        It does not determine whether consumption was valid.
        """
        return self.filter(
            is_consumed=True,
        )

    def unconsumed(self) -> "PaymentQuerySet":
        """
        Return payments that have not been consumed.
        """
        return self.filter(
            is_consumed=False,
        )

    def refunded(self) -> "PaymentQuerySet":
        """
        Return payments marked as refunded.
        """
        return self.filter(
            is_refunded=True,
        )

    def not_refunded(self) -> "PaymentQuerySet":
        """
        Return payments that are not marked as refunded.
        """
        return self.filter(
            is_refunded=False,
        )

    # ------------------------
    # Common Operational Query
    # ------------------------

    def open(self) -> "PaymentQuerySet":
        """
        Return payments that are still operationally open.

        IMPORTANT
        ---------
        The current PaymentModel does not define a closed_date
        field.

        Therefore this method MUST NOT reference closed_date.

        For the current Payment state machine:
            PENDING = open
            SUCCESS = terminal
            FAILED  = terminal

        This method intentionally remains a persistence query.

        It does NOT mean:
            "payment is legally payable"

        or:
            "payment can be initiated"

        Those decisions belong to PaymentPolicy.
        """
        return self.filter(
            status=PaymentStatusType.PENDING,
        )

    def completed(self) -> "PaymentQuerySet":
        """
        Return payments that reached successful + consumed state.
        This is a structural query predicate.
        It does NOT determine whether the payment is eligible
        for any further business operation.
        """
        return self.filter(
            status=PaymentStatusType.SUCCESS,
            is_consumed=True,
        )

    # ------------------------
    # Order Scope
    # ------------------------

    def for_order(
        self,
        order,
    ) -> "PaymentQuerySet":
        """
        Return payments belonging to an Order.

        Accepts either:
            OrderModel instance

        or:
            order primary key
        """
        if hasattr(order, "pk"):
            return self.filter(
                order_id=order.pk,
            )

        return self.filter(
            order_id=order,
        )

    def for_order_id(
        self,
        order_id: int,
    ) -> "PaymentQuerySet":
        """
        Explicit order-id variant.

        Useful inside repositories where the persistence
        contract is expressed in primitive identifiers.
        """
        return self.filter(
            order_id=order_id,
        )

    # ------------------------
    # Gateway Scope
    # ------------------------

    def by_gateway(
        self,
        gateway: str,
    ) -> "PaymentQuerySet":
        """
        Return payments using the specified gateway.
        """
        return self.filter(
            gateway=gateway,
        )

    # ------------------------
    # Deterministic Ordering
    # ------------------------

    def newest_first(self) -> "PaymentQuerySet":
        """
        Deterministic newest-first ordering.
        created_date alone is not sufficient for deterministic
        ordering when timestamps collide.
        Therefore id is used as a stable tie-breaker.
        """
        return self.order_by(
            "-created_date",
            "-id",
        )

    def oldest_first(self) -> "PaymentQuerySet":
        """
        Deterministic oldest-first ordering.
        """
        return self.order_by(
            "created_date",
            "id",
        )

    # ------------------------
    # Locking
    # ------------------------

    def for_update(self) -> "PaymentQuerySet":
        """
        Apply SELECT ... FOR UPDATE.
        Transaction ownership remains with the caller.
        This method does NOT call transaction.atomic().
        """
        return self.select_for_update()

    def for_update_skip_locked(self) -> "PaymentQuerySet":
        """
        Apply SELECT ... FOR UPDATE SKIP LOCKED.
        Intended for worker/reconciliation style processing.
        Transaction ownership remains with the caller.
        """
        return self.select_for_update(
            skip_locked=True,
        )

    # ------------------------
    # Related Object Loading
    # ------------------------

    def with_order(self) -> "PaymentQuerySet":
        """
        Load Order using SELECT RELATED.
        This is a query optimization only.
        """
        return self.select_related(
            "order",
        )

# ================================
# Payment Manager
# ================================

class PaymentManager(
    models.Manager.from_queryset(PaymentQuerySet),
):
    """
    Manager for PaymentModel.
    Business logic MUST NOT be placed here.
    
    Keeping the Manager intentionally empty also makes the
    architectural boundary obvious:
        QuerySet -> query composition
        Manager -> entry point
        Repository -> persistence boundary
        Policy -> business decision
        Service -> workflow
    """

    pass

# ================================
# PaymentAttempt QuerySet
# ================================

class PaymentAttemptQuerySet(models.QuerySet):
    """
    Persistence/query API for PaymentAttempt.
    PaymentAttempt is a child entity of Payment.

    No method here may:
        - create retry attempts
        - allocate attempt numbers
        - decide retry eligibility
        - verify a gateway transaction
        - mutate Payment
        - mutate Order
    """

    # ------------------------
    # State Queries
    # ------------------------

    def pending(self) -> "PaymentAttemptQuerySet":
        """
        Return pending attempts.
        """
        return self.filter(
            status=PaymentAttemptStatus.PENDING,
        )

    def successful(self) -> "PaymentAttemptQuerySet":
        """
        Return successful attempts.
        """
        return self.filter(
            status=PaymentAttemptStatus.SUCCESS,
        )

    def failed(self) -> "PaymentAttemptQuerySet":
        """
        Return failed attempts.
        """
        return self.filter(
            status=PaymentAttemptStatus.FAILED,
        )

    def timeout(self) -> "PaymentAttemptQuerySet":
        """
        Return timed-out attempts.
        """
        return self.filter(
            status=PaymentAttemptStatus.TIMEOUT,
        )

    def cancelled(self) -> "PaymentAttemptQuerySet":
        """
        Return cancelled attempts.
        """
        return self.filter(
            status=PaymentAttemptStatus.CANCELLED,
        )

    # ------------------------
    # Terminal State Query
    # ------------------------

    def terminal(self) -> "PaymentAttemptQuerySet":
        """
        Return attempts in any terminal state.

        Terminal states:
            SUCCESS
            FAILED
            TIMEOUT
            CANCELLED
        """
        return self.filter(
            status__in=[
                PaymentAttemptStatus.SUCCESS,
                PaymentAttemptStatus.FAILED,
                PaymentAttemptStatus.TIMEOUT,
                PaymentAttemptStatus.CANCELLED,
            ],
        )

    # ------------------------
    # Payment Scope
    # ------------------------

    def for_payment(
        self,
        payment,
    ) -> "PaymentAttemptQuerySet":
        """
        Return attempts belonging to a Payment.

        Accepts either:
            PaymentModel instance

        or:
            payment primary key.
        """
        if hasattr(payment, "pk"):
            return self.filter(
                payment_id=payment.pk,
            )

        return self.filter(
            payment_id=payment,
        )

    def for_payment_id(
        self,
        payment_id: int,
    ) -> "PaymentAttemptQuerySet":
        """
        Explicit payment-id query.
        """
        return self.filter(
            payment_id=payment_id,
        )

    # ------------------------
    # Deterministic Ordering
    # ------------------------

    def ordered_latest(self) -> "PaymentAttemptQuerySet":
        """
        Return newest attempt first.
        attempt_number is the logical sequence.
        id is retained as a deterministic tie-breaker.
        """
        return self.order_by(
            "-attempt_number",
            "-id",
        )

    def ordered_oldest(self) -> "PaymentAttemptQuerySet":
        """
        Return oldest attempt first.
        """
        return self.order_by(
            "attempt_number",
            "id",
        )

    # ------------------------
    # Operational Queries
    # ------------------------

    def with_authority(
        self,
        authority_id: str,
    ) -> "PaymentAttemptQuerySet":
        """
        Filter by gateway authority.
        This is only a query predicate.
        It does NOT assume global uniqueness.
        """
        return self.filter(
            authority_id=authority_id,
        )

    def with_gateway_reference(
        self,
        gateway_reference: str,
    ) -> "PaymentAttemptQuerySet":
        """
        Filter by gateway reference.

        Scope must normally be constrained by Payment when the
        database does not guarantee global uniqueness.
        """
        return self.filter(
            gateway_reference=gateway_reference,
        )

    def with_gateway_transaction_id(
        self,
        gateway_transaction_id: str,
    ) -> "PaymentAttemptQuerySet":
        """
        Filter by gateway transaction identifier.
        """
        return self.filter(
            gateway_transaction_id=gateway_transaction_id,
        )

    # ------------------------
    # Locking
    # ------------------------

    def for_update(self) -> "PaymentAttemptQuerySet":
        """
        Apply SELECT ... FOR UPDATE.
        """
        return self.select_for_update()

    def for_update_skip_locked(self) -> "PaymentAttemptQuerySet":
        """
        Apply SELECT ... FOR UPDATE SKIP LOCKED.
        """
        return self.select_for_update(
            skip_locked=True,
        )

    # ------------------------
    # Related Object Loading
    # ------------------------

    def with_payment(self) -> "PaymentAttemptQuerySet":
        """
        Load Payment using SELECT RELATED.
        """
        return self.select_related(
            "payment",
        )

# ================================
# PaymentAttempt Manager
# ================================

class PaymentAttemptManager(
    models.Manager.from_queryset(
        PaymentAttemptQuerySet,
    ),
):
    """
    Manager for PaymentAttempt.
    Intentionally contains no business workflow.
    """

    pass


# ================================
# Refund QuerySet
# ================================


class RefundQuerySet(models.QuerySet):
    """
    Query composition API for Refund.
    Refund business rules belong to RefundPolicy / RefundService.
    """

    # ------------------------
    # State
    # ------------------------

    def pending(self) -> "RefundQuerySet":
        """
        Return pending refunds.
        """
        return self.filter(
            status=RefundStatus.PENDING,
        )

    def successful(self) -> "RefundQuerySet":
        """
        Return successful refunds.
        """
        return self.filter(
            status=RefundStatus.SUCCESS,
        )

    def failed(self) -> "RefundQuerySet":
        """
        Return failed refunds.
        """
        return self.filter(
            status=RefundStatus.FAILED,
        )

    def terminal(self) -> "RefundQuerySet":
        """
        Return terminal refunds.
        """
        return self.filter(
            status__in=[
                RefundStatus.SUCCESS,
                RefundStatus.FAILED,
            ],
        )

    # ------------------------
    # Payment Scope
    # ------------------------

    def for_payment(
        self,
        payment,
    ) -> "RefundQuerySet":
        """
        Return refunds belonging to a Payment.
        """
        if hasattr(payment, "pk"):
            return self.filter(
                payment_id=payment.pk,
            )

        return self.filter(
            payment_id=payment,
        )

    def for_payment_id(
        self,
        payment_id: int,
    ) -> "RefundQuerySet":
        """
        Explicit payment-id query.
        """
        return self.filter(
            payment_id=payment_id,
        )

    # ------------------------
    # Idempotency
    # ------------------------

    def by_idempotency_key(
        self,
        idempotency_key,
    ) -> "RefundQuerySet":
        """
        Find a refund by its application-level idempotency key.
        """
        return self.filter(
            idempotency_key=idempotency_key,
        )

    # ------------------------
    # Gateway Scope
    # ------------------------

    def by_gateway(
        self,
        gateway: str,
    ) -> "RefundQuerySet":
        """
        Return refunds using a specific gateway.
        """
        return self.filter(
            payment__gateway=gateway,
        )

    def with_gateway_reference(
        self,
        gateway_reference: str,
    ) -> "RefundQuerySet":
        """
        Filter by gateway refund reference.
        """
        return self.filter(
            gateway_reference=gateway_reference,
        )

    def with_gateway_transaction_id(
        self,
        gateway_transaction_id: str,
    ) -> "RefundQuerySet":
        """
        Filter by gateway transaction identifier.
        """
        return self.filter(
            gateway_transaction_id=gateway_transaction_id,
        )

    # ------------------------
    # Ordering
    # ------------------------

    def newest_first(self) -> "RefundQuerySet":
        """
        Deterministic newest-first ordering.
        """
        return self.order_by(
            "-created_date",
            "-id",
        )

    def oldest_first(self) -> "RefundQuerySet":
        """
        Deterministic oldest-first ordering.
        """
        return self.order_by(
            "created_date",
            "id",
        )

    # ------------------------
    # Locking
    # ------------------------

    def for_update(self) -> "RefundQuerySet":
        """
        Apply SELECT ... FOR UPDATE.
        """
        return self.select_for_update()

    def for_update_skip_locked(self) -> "RefundQuerySet":
        """
        Apply SELECT ... FOR UPDATE SKIP LOCKED.
        """
        return self.select_for_update(
            skip_locked=True,
        )

    # ------------------------
    # Related Object Loading
    # ------------------------

    def with_payment(self) -> "RefundQuerySet":
        """
        Load Payment using SELECT RELATED.
        """
        return self.select_related(
            "payment",
        )

# ================================
# Refund Manager
# ================================

class RefundManager(
    models.Manager.from_queryset(
        RefundQuerySet,
    ),
):
    """
    Manager for Refund.
    Intentionally contains no business workflow.
    """

    pass

# ================================
# GatewayLog QuerySet
# ================================

class GatewayLogQuerySet(models.QuerySet):
    """
    Persistence/query API for GatewayLog.
    GatewayLog is an audit record.
    QuerySet methods may classify records by technical
    direction/type, but must not execute gateway behavior.
    """

    # ------------------------
    # Direction
    # ------------------------

    def inbound(self) -> "GatewayLogQuerySet":
        """
        Return inbound gateway communication records.
        """
        return self.filter(
            direction=GatewayLogDirection.INBOUND,
        )

    def outbound(self) -> "GatewayLogQuerySet":
        """
        Return outbound gateway communication records.
        """
        return self.filter(
            direction=GatewayLogDirection.OUTBOUND,
        )

    # ------------------------
    # Communication Type
    # ------------------------

    def requests(self) -> "GatewayLogQuerySet":
        """
        Return outbound/request log records.
        """
        return self.filter(
            log_type=GatewayLogType.REQUEST,
        )

    def responses(self) -> "GatewayLogQuerySet":
        """
        Return response log records.
        """
        return self.filter(
            log_type=GatewayLogType.RESPONSE,
        )

    def callbacks(self) -> "GatewayLogQuerySet":
        """
        Return callback records.
        """
        return self.filter(
            log_type=GatewayLogType.CALLBACK,
        )

    def verifications(self) -> "GatewayLogQuerySet":
        """
        Return verification records.
        """
        return self.filter(
            log_type=GatewayLogType.VERIFY,
        )

    def refunds(self) -> "GatewayLogQuerySet":
        """
        Return refund communication records.
        """
        return self.filter(
            log_type=GatewayLogType.REFUND,
        )

    def webhooks(self) -> "GatewayLogQuerySet":
        """
        Return webhook records.
        """
        return self.filter(
            log_type=GatewayLogType.WEBHOOK,
        )

    def errors(self) -> "GatewayLogQuerySet":
        """
        Return technical error records.
        """
        return self.filter(
            log_type=GatewayLogType.ERROR,
        )

    # ------------------------
    # Ownership
    # ------------------------

    def for_attempt(
        self,
        attempt,
    ) -> "GatewayLogQuerySet":
        """
        Return logs belonging to a PaymentAttempt.
        """
        if hasattr(attempt, "pk"):
            return self.filter(
                attempt_id=attempt.pk,
            )

        return self.filter(
            attempt_id=attempt,
        )

    def for_refund(
        self,
        refund,
    ) -> "GatewayLogQuerySet":
        """
        Return logs belonging to a Refund.
        """
        if hasattr(refund, "pk"):
            return self.filter(
                refund_id=refund.pk,
            )

        return self.filter(
            refund_id=refund,
        )

    # ------------------------
    # Gateway
    # ------------------------

    def by_gateway(
        self,
        gateway: str,
    ) -> "GatewayLogQuerySet":
        """
        Return logs generated by a specific gateway.
        """
        return self.filter(
            gateway=gateway,
        )

    # ------------------------
    # Ordering
    # ------------------------

    def newest_first(self) -> "GatewayLogQuerySet":
        """
        Deterministic newest-first ordering.

        The exact timestamp field is intentionally not assumed here.
        GatewayLog's model ordering remains authoritative until the
        audit model contract is frozen.
        """
        return self.order_by(
            "-id",
        )

    def oldest_first(self) -> "GatewayLogQuerySet":
        """
        Deterministic oldest-first ordering.
        """
        return self.order_by(
            "id",
        )

# ================================
# GatewayLog Manager
# ================================

class GatewayLogManager(
    models.Manager.from_queryset(
        GatewayLogQuerySet,
    ),
):
    """
    Manager for GatewayLog.
    Intentionally contains no gateway behavior.
    """
    
    pass
