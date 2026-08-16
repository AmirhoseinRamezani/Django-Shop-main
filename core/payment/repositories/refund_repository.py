# core/payment/repositories/refund_repository.py
# core/payment/repositories/refund_repository.py

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

from django.db.models import QuerySet, Sum

from payment.enums import RefundStatus
from payment.models.refund import Refund
from payment.repositories.base import BaseRepository


class RefundRepository(
    BaseRepository[Refund],
):
    """
    Persistence boundary for Refund.

    Responsibilities
    ----------------
    - Refund persistence
    - Refund queries
    - Payment-scoped queries
    - row locking
    - cumulative successful-refund aggregation
    - idempotency lookup
    - gateway evidence persistence

    Non-responsibilities
    --------------------
    - refund authorization
    - refund state-machine decisions
    - gateway communication
    - provider-specific parsing
    - transaction ownership
    - Payment state transitions
    - event publication
    - business policy

    Concurrency contract
    --------------------
    Payment is the canonical synchronization point for cumulative
    refund authorization.

    RefundRepository does not implicitly lock Payment.

    RefundService is responsible for:

        transaction.atomic()
            ->
        PaymentRepository.get_for_update()
            ->
        RefundRepository queries
            ->
        gateway execution
            ->
        Refund persistence
            ->
        Payment synchronization

    Idempotency
    -----------
    The database uniqueness constraint on idempotency_key is authoritative.
    Repository-level lookup is used for reconciliation, while the database
    remains the final concurrency authority.

    Financial aggregation
    ---------------------
    successful_amount_for_payment() includes only SUCCESS refunds.

    PENDING and FAILED refunds never contribute to the refundable balance.
    """

    model: ClassVar[type[Refund]] = Refund

    # ================================
    # STATUS GROUPS
    # ================================

    SUCCESS_STATUSES: ClassVar[
        tuple[str, ...]
    ] = (
        RefundStatus.SUCCESS,
    )

    TERMINAL_STATUSES: ClassVar[
        tuple[str, ...]
    ] = (
        RefundStatus.SUCCESS,
        RefundStatus.FAILED,
    )

    ACTIVE_STATUSES: ClassVar[
        tuple[str, ...]
    ] = (
        RefundStatus.PENDING,
    )

    # ================================
    # STRUCTURAL FIELDS
    # ================================

    STRUCTURAL_FIELDS: ClassVar[
        frozenset[str]
    ] = frozenset(
        {
            "payment",
            "payment_id",
            "amount",
            "currency",
            "idempotency_key",
            "reason",
            "reason_detail",
        }
    )

    SAFE_UPDATE_FIELDS: ClassVar[
        tuple[str, ...]
    ] = (
        "status",
        "gateway_reference",
        "gateway_transaction_id",
        "response_code",
        "gateway_message",
        "failure_reason",
        "finished_at",
        "latency_ms",
        "ip_address",
        "user_agent",
        "meta",
    )

    GATEWAY_EVIDENCE_FIELDS: ClassVar[
        tuple[str, ...]
    ] = (
        "response_code",
        "gateway_message",
        "latency_ms",
    )

    SUCCESS_UPDATE_FIELDS: ClassVar[
        tuple[str, ...]
    ] = (
        "status",
        "gateway_reference",
        "gateway_transaction_id",
        "response_code",
        "gateway_message",
        "failure_reason",
        "finished_at",
        "latency_ms",
    )

    FAILURE_UPDATE_FIELDS: ClassVar[
        tuple[str, ...]
    ] = (
        "status",
        "response_code",
        "gateway_message",
        "failure_reason",
        "finished_at",
        "latency_ms",
    )

    # ================================
    # QUERYSET
    # ================================

    @classmethod
    def queryset(
        cls,
    ) -> QuerySet[Refund]:
        """
        Return the base lazy Refund QuerySet.

        No transaction.
        No locking.
        No business filtering.
        """

        return cls.model.objects.all()

    # ================================
    # BASIC READ
    # ================================

    @classmethod
    def get(
        cls,
        refund_id: int,
    ) -> Refund:
        """
        Retrieve one Refund.

        DoesNotExist intentionally propagates.
        """

        return cls.queryset().get(
            pk=refund_id,
        )

    @classmethod
    def find(
        cls,
        refund_id: int,
    ) -> Refund | None:
        """
        Retrieve one Refund if it exists.
        """

        return (
            cls.queryset()
            .filter(
                pk=refund_id,
            )
            .first()
        )

    # ================================
    # LOCKING
    # ================================

    @classmethod
    def get_for_update(
        cls,
        refund_id: int,
    ) -> Refund:
        """
        Lock one Refund.
        Caller owns transaction.atomic().
        """

        return (
            cls.queryset()
            .select_for_update()
            .get(
                pk=refund_id,
            )
        )

    @classmethod
    def find_for_update(
        cls,
        refund_id: int,
    ) -> Refund | None:
        """
        Lock one Refund if it exists.
        """

        return (
            cls.queryset()
            .filter(
                pk=refund_id,
            )
            .select_for_update()
            .first()
        )

    @classmethod
    def get_for_update_nowait(
        cls,
        refund_id: int,
    ) -> Refund:
        """
        Lock one Refund using NOWAIT.
        """

        return (
            cls.queryset()
            .select_for_update(
                nowait=True,
            )
            .get(
                pk=refund_id,
            )
        )

    # ================================
    # IDEMPOTENCY
    # ================================

    @staticmethod
    def _normalize_idempotency_key(
        value: str | None,
    ) -> str:
        return str(
            value or "",
        ).strip()

    @classmethod
    def find_by_idempotency_key(
        cls,
        idempotency_key: str,
    ) -> Refund | None:
        """
        Find a Refund by its globally unique idempotency identity.

        Empty keys return None instead of performing an accidental query.
        """

        normalized = cls._normalize_idempotency_key(
            idempotency_key,
        )

        if not normalized:
            return None

        return (
            cls.queryset()
            .filter(
                idempotency_key=normalized,
            )
            .first()
        )

    @classmethod
    def find_by_idempotency_key_for_update(
        cls,
        idempotency_key: str,
    ) -> Refund | None:
        """
        Find and lock a Refund by idempotency identity.

        Caller owns transaction.atomic().
        """

        normalized = cls._normalize_idempotency_key(
            idempotency_key,
        )

        if not normalized:
            return None

        return (
            cls.queryset()
            .filter(
                idempotency_key=normalized,
            )
            .select_for_update()
            .first()
        )

    # ================================
    # PAYMENT-SCOPED QUERIES
    # ================================

    @classmethod
    def for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return Refunds belonging to one Payment.

        Newest Refund first.
        """

        return (
            cls.queryset()
            .filter(
                payment_id=payment_id,
            )
            .order_by(
                "-created_at",
                "-id",
            )
        )

    @classmethod
    def for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return Payment Refunds with row locks.

        Payment locking remains the responsibility of the Service.
        """

        return (
            cls.for_payment(
                payment_id,
            )
            .select_for_update()
        )

    @classmethod
    def count_for_payment(
        cls,
        payment_id: int,
    ) -> int:
        return cls.for_payment(
            payment_id,
        ).count()

    @classmethod
    def exists_for_payment(
        cls,
        payment_id: int,
    ) -> bool:
        return cls.for_payment(
            payment_id,
        ).exists()

    @classmethod
    def latest_for_payment(
        cls,
        payment_id: int,
    ) -> Refund | None:
        return cls.for_payment(
            payment_id,
        ).first()

    # ================================
    # STATUS QUERIES
    # ================================

    @classmethod
    def _for_status(
        cls,
        payment_id: int,
        status: str,
    ) -> QuerySet[Refund]:
        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                status=status,
            )
        )

    @classmethod
    def pending_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        return cls._for_status(
            payment_id,
            RefundStatus.PENDING,
        )

    @classmethod
    def successful_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        return cls._for_status(
            payment_id,
            RefundStatus.SUCCESS,
        )

    @classmethod
    def failed_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        return cls._for_status(
            payment_id,
            RefundStatus.FAILED,
        )

    @classmethod
    def terminal_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                status__in=cls.TERMINAL_STATUSES,
            )
        )

    @classmethod
    def active_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                status__in=cls.ACTIVE_STATUSES,
            )
        )

    # ================================
    # STATUS LOOKUPS
    # ================================

    @classmethod
    def latest_pending_for_payment(
        cls,
        payment_id: int,
    ) -> Refund | None:
        return cls.pending_for_payment(
            payment_id,
        ).first()

    @classmethod
    def latest_successful_for_payment(
        cls,
        payment_id: int,
    ) -> Refund | None:
        return cls.successful_for_payment(
            payment_id,
        ).first()

    @classmethod
    def latest_failed_for_payment(
        cls,
        payment_id: int,
    ) -> Refund | None:
        return cls.failed_for_payment(
            payment_id,
        ).first()

    # ================================
    # GLOBAL STATUS QUERIES
    # ================================

    @classmethod
    def pending_all(
        cls,
    ) -> QuerySet[Refund]:
        return cls.queryset().filter(
            status=RefundStatus.PENDING,
        )

    @classmethod
    def successful_all(
        cls,
    ) -> QuerySet[Refund]:
        return cls.queryset().filter(
            status=RefundStatus.SUCCESS,
        )

    @classmethod
    def failed_all(
        cls,
    ) -> QuerySet[Refund]:
        return cls.queryset().filter(
            status=RefundStatus.FAILED,
        )

    @classmethod
    def terminal_all(
        cls,
    ) -> QuerySet[Refund]:
        return cls.queryset().filter(
            status__in=cls.TERMINAL_STATUSES,
        )

    # ================================
    # REFUND AGGREGATION
    # ================================

    @classmethod
    def successful_amount_for_payment(
        cls,
        payment_id: int,
    ) -> Decimal:
        """
        Return the authoritative cumulative successful refund amount.

        Only SUCCESS Refunds contribute.

        NULL aggregation is normalized to Decimal("0").

        This method performs no locking itself.

        RefundService must hold the canonical Payment lock before using
        this value for refund authorization.
        """

        result = (
            cls.successful_for_payment(
                payment_id,
            )
            .aggregate(
                total=Sum(
                    "amount",
                ),
            )
        )

        total = result.get(
            "total",
        )

        if total is None:
            return Decimal("0")

        return Decimal(
            total,
        )

    # ================================
    # AMOUNT QUERIES
    # ================================

    @classmethod
    def successful_count_for_payment(
        cls,
        payment_id: int,
    ) -> int:
        return cls.successful_for_payment(
            payment_id,
        ).count()

    @classmethod
    def pending_count_for_payment(
        cls,
        payment_id: int,
    ) -> int:
        return cls.pending_for_payment(
            payment_id,
        ).count()

    @classmethod
    def failed_count_for_payment(
        cls,
        payment_id: int,
    ) -> int:
        return cls.failed_for_payment(
            payment_id,
        ).count()

    # ================================
    # GATEWAY IDENTITY
    # ================================

    @staticmethod
    def _normalize_identity(
        value: str | None,
    ) -> str:
        return str(
            value or "",
        ).strip()

    @classmethod
    def find_by_gateway_reference(
        cls,
        gateway_reference: str,
    ) -> Refund | None:
        reference = cls._normalize_identity(
            gateway_reference,
        )

        if not reference:
            return None

        return (
            cls.queryset()
            .filter(
                gateway_reference=reference,
            )
            .first()
        )

    @classmethod
    def find_by_gateway_reference_for_update(
        cls,
        gateway_reference: str,
    ) -> Refund | None:
        reference = cls._normalize_identity(
            gateway_reference,
        )

        if not reference:
            return None

        return (
            cls.queryset()
            .filter(
                gateway_reference=reference,
            )
            .select_for_update()
            .first()
        )

    @classmethod
    def find_by_gateway_transaction_id(
        cls,
        gateway_transaction_id: str,
    ) -> Refund | None:
        transaction_id = cls._normalize_identity(
            gateway_transaction_id,
        )

        if not transaction_id:
            return None

        return (
            cls.queryset()
            .filter(
                gateway_transaction_id=transaction_id,
            )
            .first()
        )

    @classmethod
    def find_by_gateway_transaction_id_for_update(
        cls,
        gateway_transaction_id: str,
    ) -> Refund | None:
        transaction_id = cls._normalize_identity(
            gateway_transaction_id,
        )

        if not transaction_id:
            return None

        return (
            cls.queryset()
            .filter(
                gateway_transaction_id=transaction_id,
            )
            .select_for_update()
            .first()
        )

    # ================================
    # CREATION
    # ================================

    @classmethod
    def create(
        cls,
        **kwargs: Any,
    ) -> Refund:
        """
        Create one immutable Refund snapshot.

        IntegrityError intentionally propagates.

        The caller owns:

            - transaction.atomic()
            - Payment locking
            - financial authorization
            - business policy
        """

        return cls.model.objects.create(
            **kwargs,
        )

    # ================================
    # PERSISTENCE
    # ================================

    @classmethod
    def save(
        cls,
        refund: Refund,
        *,
        update_fields: list[str] | tuple[str, ...] | None = None,
    ) -> Refund:
        """
        Persist mutable Refund fields.

        Immutable financial/request identity cannot be changed through
        this method.
        """

        if refund.pk is None:
            raise ValueError(
                "Cannot persist an unsaved Refund."
            )

        fields = (
            list(cls.SAFE_UPDATE_FIELDS)
            if update_fields is None
            else list(update_fields)
        )

        if not fields:
            raise ValueError(
                "RefundRepository.save() requires "
                "at least one update field."
            )

        forbidden = cls.STRUCTURAL_FIELDS.intersection(
            fields,
        )

        if forbidden:
            raise ValueError(
                "Refund structural fields cannot be modified "
                "through RefundRepository.save(): "
                + ", ".join(
                    sorted(forbidden),
                )
            )

        unsupported = set(fields).difference(
            cls.SAFE_UPDATE_FIELDS,
        )

        if unsupported:
            raise ValueError(
                "Unsupported Refund update fields: "
                + ", ".join(
                    sorted(unsupported),
                )
            )

        refund.save(
            update_fields=fields,
        )

        return refund

    # ================================
    # REQUEST OBSERVABILITY
    # ================================

    @classmethod
    def save_request_context(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist non-financial request metadata.
        """

        return cls.save(
            refund,
            update_fields=(
                "ip_address",
                "user_agent",
                "meta",
            ),
        )

    # ================================
    # GATEWAY EVIDENCE
    # ================================

    @classmethod
    def save_gateway_evidence(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist safe normalized gateway evidence.

        Raw provider payloads are intentionally outside this repository.
        """

        return cls.save(
            refund,
            update_fields=cls.GATEWAY_EVIDENCE_FIELDS,
        )

    # ================================
    # SUCCESS / FAILURE
    # ================================

    @classmethod
    def save_success(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist a successful Refund transition.

        State legality is enforced by Refund.mark_success().
        """

        return cls.save(
            refund,
            update_fields=cls.SUCCESS_UPDATE_FIELDS,
        )

    @classmethod
    def save_failure(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist a deterministic failed Refund transition.

        State legality is enforced by Refund.mark_failed().
        """

        return cls.save(
            refund,
            update_fields=cls.FAILURE_UPDATE_FIELDS,
        )

    # ================================
    # PENDING / RECONCILIATION
    # ================================

    @classmethod
    def stale_pending(
        cls,
        *,
        created_before,
    ) -> QuerySet[Refund]:
        """
        Return old pending Refunds as reconciliation candidates.

        Candidate selection only.

        No financial decision is made here.
        """

        return (
            cls.pending_all()
            .filter(
                created_at__lt=created_before,
            )
            .order_by(
                "created_at",
                "id",
            )
        )

    @classmethod
    def stale_pending_for_update_skip_locked(
        cls,
        *,
        created_before,
    ) -> QuerySet[Refund]:
        """
        Return stale pending Refunds with SKIP LOCKED.

        Intended for reconciliation workers.

        Caller owns transaction.atomic().
        """

        return (
            cls.stale_pending(
                created_before=created_before,
            )
            .select_for_update(
                skip_locked=True,
            )
        )

    # ================================
    # PAYMENT REFUND STATE SUPPORT
    # ================================

    @classmethod
    def is_fully_refunded(
        cls,
        *,
        payment_id: int,
        payment_amount: Decimal,
    ) -> bool:
        """
        Return whether successful refunds exactly equal Payment amount.

        This is an aggregate query helper.

        It does not mutate Payment and does not constitute the business
        policy itself.
        """

        total = cls.successful_amount_for_payment(
            payment_id,
        )

        return total == payment_amount

    @classmethod
    def has_refundable_balance(
        cls,
        *,
        payment_id: int,
        payment_amount: Decimal,
    ) -> bool:
        """
        Return whether any successful-refund balance remains.
        """

        total = cls.successful_amount_for_payment(
            payment_id,
        )

        return total < payment_amount

    @classmethod
    def remaining_refundable_amount(
        cls,
        *,
        payment_id: int,
        payment_amount: Decimal,
    ) -> Decimal:
        """
        Calculate the remaining refundable amount from persisted SUCCESS
        Refunds.

        The caller is responsible for ensuring payment_amount is valid.
        """

        refunded = cls.successful_amount_for_payment(
            payment_id,
        )

        remaining = (
            payment_amount - refunded
        )

        if remaining <= Decimal("0"):
            return Decimal("0")

        return remaining

    # ================================
    # REPRESENTATION
    # ================================

    def __repr__(self) -> str:
        return (
            f"<RefundRepository "
            f"model={self.model.__name__}>"
        )