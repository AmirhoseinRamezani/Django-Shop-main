# core/payment/repositories/refund_repository.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

from django.db.models import QuerySet, Sum

from payment.enums import RefundStatus
from payment.models.refund import Refund
from payment.repositories.base import BaseRepository


class RefundRepository(BaseRepository[Refund]):
    """
    Persistence boundary for Refund.

    Responsibilities
    ----------------
    This repository owns only database-oriented Refund operations:

        - QuerySets
        - retrieval
        - payment-scoped queries
        - row locking
        - idempotency lookup
        - gateway identity lookup
        - successful-refund aggregation
        - persistence of already-decided domain state
        - reconciliation candidate selection

    It does NOT own:

        - transaction boundaries
        - refund authorization
        - cumulative refund policy
        - Payment state transitions
        - Refund state transitions
        - gateway communication
        - retry policy
        - event publication
        - business decisions

    Concurrency
    -----------
    Payment is the canonical synchronization point for cumulative refund
    authorization.

    RefundRepository may lock Refund rows when the caller explicitly
    requests it, but Refund locking never replaces Payment locking for
    aggregate-level refund authorization.

    Transaction ownership
    ---------------------
    This repository never opens transaction.atomic().

    The application service owns transaction boundaries.
    """

    model: ClassVar[type[Refund]] = Refund

    # --------------------------------------------
    # Status groups
    # --------------------------------------------

    SUCCESS_STATUSES: ClassVar[tuple[str, ...]] = (
        RefundStatus.SUCCESS,
    )

    TERMINAL_STATUSES: ClassVar[tuple[str, ...]] = (
        RefundStatus.SUCCESS,
        RefundStatus.FAILED,
    )

    ACTIVE_STATUSES: ClassVar[tuple[str, ...]] = (
        RefundStatus.PENDING,
    )

    # --------------------------------------------
    # Persistence contracts
    # --------------------------------------------

    STRUCTURAL_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "payment",
            "payment_id",
            "amount",
            "currency",
            "idempotency_key",
            "reason",
            "reason_detail",
            "requested_at",
        }
    )

    SAFE_UPDATE_FIELDS: ClassVar[tuple[str, ...]] = (
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

    REQUEST_CONTEXT_FIELDS: ClassVar[tuple[str, ...]] = (
        "ip_address",
        "user_agent",
        "meta",
    )

    GATEWAY_EVIDENCE_FIELDS: ClassVar[tuple[str, ...]] = (
        "response_code",
        "gateway_message",
        "latency_ms",
    )

    SUCCESS_UPDATE_FIELDS: ClassVar[tuple[str, ...]] = (
        "status",
        "gateway_reference",
        "gateway_transaction_id",
        "response_code",
        "gateway_message",
        "failure_reason",
        "finished_at",
        "latency_ms",
    )

    FAILURE_UPDATE_FIELDS: ClassVar[tuple[str, ...]] = (
        "status",
        "response_code",
        "gateway_message",
        "failure_reason",
        "finished_at",
        "latency_ms",
    )

    # ============================
    # BASE QUERYSET
    # ============================

    @classmethod
    def queryset(cls) -> QuerySet[Refund]:
        """
        Return the base lazy Refund QuerySet.

        No:

            - transaction
            - locking
            - business policy
        """
        return cls.model.objects.all()

    # ============================
    # BASIC READ
    # ============================

    @classmethod
    def get(
        cls,
        refund_id: int,
    ) -> Refund:
        """
        Retrieve one Refund.

        Django's DoesNotExist exception intentionally propagates.
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

    # ============================
    # LOCKING
    # ============================

    @classmethod
    def get_for_update(
        cls,
        refund_id: int,
    ) -> Refund:
        """
        Lock one Refund row.

        The caller owns transaction.atomic().
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
        Lock one Refund row if it exists.

        The caller owns transaction.atomic().
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
        Lock one Refund row using PostgreSQL NOWAIT semantics.

        The caller owns transaction.atomic().
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

    # ============================
    # IDEMPOTENCY
    # ============================

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
        Find a Refund by its globally unique idempotency key.

        Empty keys intentionally perform no database query.
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
        Find and lock a Refund by idempotency key.

        The caller owns transaction.atomic().
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

    # ============================
    # PAYMENT-SCOPED QUERIES
    # ============================

    @classmethod
    def for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return Refunds belonging to one Payment.

        Ordering uses the actual Refund lifecycle timestamp:
            requested_at

        This is intentionally aligned with RefundModel.
        """
        return (
            cls.queryset()
            .filter(
                payment_id=payment_id,
            )
            .order_by(
                "-requested_at",
                "-id",
            )
        )

    @classmethod
    def for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return Payment-scoped Refunds with row locks.

        Payment locking remains the responsibility of the application
        service.
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

    # ============================
    # STATUS QUERIES
    # ============================

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

    # ============================
    # LATEST STATUS QUERIES
    # ============================

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

    # ============================
    # GLOBAL STATUS QUERIES
    # ============================

    @classmethod
    def pending_all(cls) -> QuerySet[Refund]:
        return cls.queryset().filter(
            status=RefundStatus.PENDING,
        )

    @classmethod
    def successful_all(cls) -> QuerySet[Refund]:
        return cls.queryset().filter(
            status=RefundStatus.SUCCESS,
        )

    @classmethod
    def failed_all(cls) -> QuerySet[Refund]:
        return cls.queryset().filter(
            status=RefundStatus.FAILED,
        )

    @classmethod
    def terminal_all(cls) -> QuerySet[Refund]:
        return cls.queryset().filter(
            status__in=cls.TERMINAL_STATUSES,
        )

    # ============================
    # FINANCIAL AGGREGATION
    # ============================

    @classmethod
    def successful_amount_for_payment(
        cls,
        payment_id: int,
    ) -> Decimal:
        """
        Return the authoritative cumulative successful refund amount.

        Only SUCCESS refunds contribute.

        PENDING and FAILED refunds are deliberately excluded.

        IMPORTANT:
            This method does not lock anything.

        RefundService must hold the canonical Payment row lock before
        using this value for cumulative refund authorization.
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
        
    @classmethod
    def reserved_amount_for_payment(
        cls,
        payment_id: int,
    ) -> Decimal:
        """
        Return the amount currently consuming refundable capacity.

        SUCCESS + PENDING
        """

        result = (
            cls.for_payment(payment_id)
            .filter(
                status__in=(
                    RefundStatus.PENDING,
                    RefundStatus.SUCCESS,
                ),
            )
            .aggregate(
                total=Sum("amount"),
            )
        )

        total = result.get("total")

        if total is None:
            return Decimal("0")

        return Decimal(total)

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

    @classmethod
    def is_fully_refunded(
        cls,
        *,
        payment_id: int,
        payment_amount: Decimal,
    ) -> bool:
        """
        Return whether successful refunds exactly equal Payment amount.

        This method only reads the aggregate.

        It does not mutate Payment and does not authorize a new refund.
        """
        successful_total = cls.successful_amount_for_payment(
            payment_id,
        )

        return successful_total == Decimal(
            str(payment_amount),
        )

    @classmethod
    def has_refundable_balance(
        cls,
        *,
        payment_id: int,
        payment_amount: Decimal,
    ) -> bool:
        """
        Return whether any refundable balance remains.

        This is a read helper only.

        Authorization still belongs to RefundService while Payment is
        locked.
        """
        successful_total = cls.successful_amount_for_payment(
            payment_id,
        )

        return successful_total < Decimal(
            str(payment_amount),
        )

    # ============================
    # GATEWAY IDENTITY
    # ============================

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

    # ============================
    # CREATION
    # ============================

    @classmethod
    def create(
        cls,
        **kwargs: Any,
    ) -> Refund:
        """
        Create one Refund record.

        IntegrityError intentionally propagates.

        The caller owns:

            - transaction.atomic()
            - Payment locking
            - idempotency race handling
            - refund authorization
            - business policy
        """
        return cls.model.objects.create(
            **kwargs,
        )

    # ============================
    # CONTROLLED PERSISTENCE
    # ============================

    @classmethod
    def save(
        cls,
        refund: Refund,
        *,
        update_fields: list[str] | tuple[str, ...] | None = None,
    ) -> Refund:
        """
        Persist already-decided mutable Refund state.

        Structural financial/request identity cannot be modified through
        this method.

        This guard is intentional: Refund.amount, currency, Payment and
        idempotency identity form the historical financial snapshot.
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
                "RefundRepository.save() requires at least one update field."
            )

        forbidden = cls.STRUCTURAL_FIELDS.intersection(
            fields,
        )

        if forbidden:
            raise ValueError(
                "Refund structural fields cannot be modified through "
                "RefundRepository.save(): "
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

    # ============================
    # REQUEST OBSERVABILITY
    # ============================

    @classmethod
    def save_request_context(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist request-level observability metadata.
        """
        return cls.save(
            refund,
            update_fields=cls.REQUEST_CONTEXT_FIELDS,
        )

    # ============================
    # GATEWAY EVIDENCE
    # ============================

    @classmethod
    def save_gateway_evidence(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist normalized gateway evidence for a PENDING Refund.

        Raw provider payloads belong to GatewayLog, not Refund.
        """
        return cls.save(
            refund,
            update_fields=cls.GATEWAY_EVIDENCE_FIELDS,
        )

    # ============================
    # TERMINAL PERSISTENCE
    # ============================

    @classmethod
    def save_success(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist a domain-approved SUCCESS transition.

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
        Persist a domain-approved FAILED transition.

        State legality is enforced by Refund.mark_failed().
        """
        return cls.save(
            refund,
            update_fields=cls.FAILURE_UPDATE_FIELDS,
        )

    # ============================
    # RECONCILIATION
    # ============================

    @classmethod
    def stale_pending(
        cls,
        *,
        requested_before,
    ) -> QuerySet[Refund]:
        """
        Return old PENDING Refunds as reconciliation candidates.

        This method selects candidates only.

        It does not:

            - mark them failed
            - mark them successful
            - call a gateway
            - change Payment state
        """
        return (
            cls.pending_all()
            .filter(
                requested_at__lt=requested_before,
            )
            .order_by(
                "requested_at",
                "id",
            )
        )

    @classmethod
    def stale_pending_for_update_skip_locked(
        cls,
        *,
        requested_before,
    ) -> QuerySet[Refund]:
        """
        Return stale PENDING Refunds using PostgreSQL SKIP LOCKED.

        Intended for reconciliation workers.

        Caller owns transaction.atomic().
        """
        return (
            cls.stale_pending(
                requested_before=requested_before,
            )
            .select_for_update(
                skip_locked=True,
            )
        )