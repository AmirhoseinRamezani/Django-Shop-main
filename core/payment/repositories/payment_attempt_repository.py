# core/payment/repositories/payment_attempt_repository.py

from __future__ import annotations

from typing import Any, ClassVar

from django.db.models import Max, QuerySet
from django.utils import timezone

from payment.enums import PaymentAttemptStatus
from payment.models import PaymentAttempt
from payment.repositories.base import BaseRepository


class PaymentAttemptRepository(
    BaseRepository[PaymentAttempt],
):
    """
    Persistence boundary for PaymentAttempt.

    Responsibilities
    ----------------
    - PaymentAttempt persistence
    - read/query composition
    - row locking
    - gateway identity lookup
    - retry-chain lookup
    - attempt-number lookup
    - state-specific persistence
    - low-level conditional updates

    Non-responsibilities
    --------------------
    - transaction ownership
    - payment business policy
    - retry eligibility
    - gateway communication
    - state-transition decisions
    - financial calculations
    - currency conversion
    - event publication

    Concurrency contract
    --------------------
    Payment is the canonical aggregate lock.

    A service creating or retrying an attempt must normally lock:
        Payment
            ->
        PaymentAttempt

    This repository does not acquire the Payment lock implicitly.

    Attempt numbering
    -----------------
    next_attempt_number() is informational.

    It is NOT independently concurrency-safe.

    The application service must hold the canonical Payment lock before
    using it to allocate a new attempt number.

    Database uniqueness remains authoritative.
    """

    model: ClassVar[type[PaymentAttempt]] = PaymentAttempt

    # ================================
    # STATUS GROUPS
    # ================================

    TERMINAL_STATUSES: ClassVar[
        tuple[str, ...]
    ] = (
        PaymentAttemptStatus.SUCCESS,
        PaymentAttemptStatus.FAILED,
        PaymentAttemptStatus.TIMEOUT,
        PaymentAttemptStatus.CANCELLED,
    )

    ACTIVE_STATUSES: ClassVar[
        tuple[str, ...]
    ] = (
        PaymentAttemptStatus.PENDING,
    )

    # ================================
    # STRUCTURAL / MUTABLE FIELDS
    # ================================

    STRUCTURAL_FIELDS: ClassVar[
        frozenset[str]
    ] = frozenset(
        {
            "payment",
            "payment_id",
            "attempt_number",
            "retry_of",
            "retry_of_id",
        }
    )

    SAFE_UPDATE_FIELDS: ClassVar[
        tuple[str, ...]
    ] = (
        "status",
        "authority_id",
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

    STATE_UPDATE_FIELDS: ClassVar[
        tuple[str, ...]
    ] = (
        "status",
        "authority_id",
        "gateway_reference",
        "gateway_transaction_id",
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
    ) -> QuerySet[PaymentAttempt]:
        """
        Return the base lazy QuerySet.

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
        attempt_id: int,
    ) -> PaymentAttempt:
        """
        Retrieve one PaymentAttempt.
        DoesNotExist is intentionally preserved.
        """

        return cls.queryset().get(
            pk=attempt_id,
        )

    @classmethod
    def find(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt | None:
        """
        Retrieve one PaymentAttempt if it exists.
        """

        return (
            cls.queryset()
            .filter(
                pk=attempt_id,
            )
            .first()
        )

    # ================================
    # PAYMENT-SCOPED QUERIES
    # ================================

    @classmethod
    def for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return attempts belonging to one Payment.
        Newest attempt first.
        """

        return (
            cls.queryset()
            .filter(
                payment_id=payment_id,
            )
            .order_by(
                "-attempt_number",
                "-id",
            )
        )

    @classmethod
    def count_for_payment(
        cls,
        payment_id: int,
    ) -> int:
        """
        Return the number of attempts for a Payment.
        Informational only.
        Never use this for attempt-number allocation.
        """

        return cls.for_payment(
            payment_id,
        ).count()

    @classmethod
    def latest_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Return the newest attempt for a Payment.
        """

        return cls.for_payment(
            payment_id,
        ).first()

    @classmethod
    def first_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Return the oldest attempt for a Payment.
        """

        return (
            cls.queryset()
            .filter(
                payment_id=payment_id,
            )
            .order_by(
                "attempt_number",
                "id",
            )
            .first()
        )

    # ================================
    # STATUS QUERIES
    # ================================

    @classmethod
    def _for_status(
        cls,
        payment_id: int,
        status: str,
    ) -> QuerySet[PaymentAttempt]:
        return cls.for_payment(
            payment_id,
        ).filter(
            status=status,
        )

    @classmethod
    def pending_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.PENDING,
        )

    @classmethod
    def successful_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.SUCCESS,
        )

    @classmethod
    def failed_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.FAILED,
        )

    @classmethod
    def timeout_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.TIMEOUT,
        )

    @classmethod
    def cancelled_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.CANCELLED,
        )

    @classmethod
    def active_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return currently active attempts.

        Currently only PENDING is active.
        """

        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                status__in=cls.ACTIVE_STATUSES,
            )
        )

    @classmethod
    def terminal_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return terminal attempts.
        """

        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                status__in=cls.TERMINAL_STATUSES,
            )
        )

    # ================================
    # LATEST STATUS
    # ================================

    @classmethod
    def latest_pending_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        return cls.pending_for_payment(
            payment_id,
        ).first()

    @classmethod
    def latest_successful_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        return cls.successful_for_payment(
            payment_id,
        ).first()

    @classmethod
    def latest_failed_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        return cls.failed_for_payment(
            payment_id,
        ).first()

    @classmethod
    def latest_timeout_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        return cls.timeout_for_payment(
            payment_id,
        ).first()

    @classmethod
    def latest_cancelled_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        return cls.cancelled_for_payment(
            payment_id,
        ).first()

    # ================================
    # EXISTENCE
    # ================================

    @classmethod
    def exists_for_payment(
        cls,
        payment_id: int,
    ) -> bool:
        return (
            cls.for_payment(
                payment_id,
            )
            .exists()
        )

    @classmethod
    def exists_pending(
        cls,
        payment_id: int,
    ) -> bool:
        """
        Convenience query only.

        Not a concurrency guarantee.
        """

        return cls.pending_for_payment(
            payment_id,
        ).exists()

    @classmethod
    def exists_successful(
        cls,
        payment_id: int,
    ) -> bool:
        return cls.successful_for_payment(
            payment_id,
        ).exists()

    @classmethod
    def exists_terminal(
        cls,
        payment_id: int,
    ) -> bool:
        return cls.terminal_for_payment(
            payment_id,
        ).exists()

    @classmethod
    def has_successful_attempt(
        cls,
        payment_id: int,
    ) -> bool:
        return cls.exists_successful(
            payment_id,
        )

    @classmethod
    def has_active_attempt(
        cls,
        payment_id: int,
    ) -> bool:
        return cls.exists_pending(
            payment_id,
        )

    # ================================
    # GATEWAY IDENTITY
    # ================================

    @staticmethod
    def _normalize_identity(
        value: str | None,
    ) -> str:
        """
        Normalize only surrounding whitespace.

        Provider-specific identifier semantics must not be invented by
        the repository.

        In particular this method does not:

            - lowercase
            - remove leading zeros
            - alter provider formats
            - perform type conversion beyond string normalization
        """

        return str(
            value or "",
        ).strip()

    @classmethod
    def find_by_authority(
        cls,
        *,
        payment_id: int,
        authority_id: str,
    ) -> PaymentAttempt | None:
        authority = cls._normalize_identity(
            authority_id,
        )

        if not authority:
            return None

        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                authority_id=authority,
            )
            .first()
        )

    @classmethod
    def find_by_reference(
        cls,
        *,
        payment_id: int,
        gateway_reference: str,
    ) -> PaymentAttempt | None:
        reference = cls._normalize_identity(
            gateway_reference,
        )

        if not reference:
            return None

        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                gateway_reference=reference,
            )
            .first()
        )

    @classmethod
    def find_by_transaction_id(
        cls,
        *,
        payment_id: int,
        gateway_transaction_id: str,
    ) -> PaymentAttempt | None:
        transaction_id = cls._normalize_identity(
            gateway_transaction_id,
        )

        if not transaction_id:
            return None

        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                gateway_transaction_id=transaction_id,
            )
            .first()
        )

    # ================================
    # GATEWAY IDENTITY + LOCK
    # ================================

    @classmethod
    def find_by_authority_for_update(
        cls,
        *,
        payment_id: int,
        authority_id: str,
    ) -> PaymentAttempt | None:
        authority = cls._normalize_identity(
            authority_id,
        )

        if not authority:
            return None

        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                authority_id=authority,
            )
            .select_for_update()
            .first()
        )

    @classmethod
    def find_by_reference_for_update(
        cls,
        *,
        payment_id: int,
        gateway_reference: str,
    ) -> PaymentAttempt | None:
        reference = cls._normalize_identity(
            gateway_reference,
        )

        if not reference:
            return None

        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                gateway_reference=reference,
            )
            .select_for_update()
            .first()
        )

    @classmethod
    def find_by_transaction_id_for_update(
        cls,
        *,
        payment_id: int,
        gateway_transaction_id: str,
    ) -> PaymentAttempt | None:
        transaction_id = cls._normalize_identity(
            gateway_transaction_id,
        )

        if not transaction_id:
            return None

        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                gateway_transaction_id=transaction_id,
            )
            .select_for_update()
            .first()
        )

    # ================================
    # PRIMARY KEY LOCKING
    # ================================

    @classmethod
    def get_for_update(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt:
        """
        Lock one PaymentAttempt.

        Caller owns transaction.atomic().
        """

        return (
            cls.queryset()
            .select_for_update()
            .get(
                pk=attempt_id,
            )
        )

    @classmethod
    def get_for_update_nowait(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt:
        """
        Lock one PaymentAttempt using NOWAIT.
        """

        return (
            cls.queryset()
            .select_for_update(
                nowait=True,
            )
            .get(
                pk=attempt_id,
            )
        )

    @classmethod
    def find_for_update(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt | None:
        """
        Lock one PaymentAttempt if it exists.
        """

        return (
            cls.queryset()
            .filter(
                pk=attempt_id,
            )
            .select_for_update()
            .first()
        )

    # ================================
    # PAYMENT-SCOPED LOCKING
    # ================================

    @classmethod
    def for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        return (
            cls.for_payment(
                payment_id,
            )
            .select_for_update()
        )

    @classmethod
    def pending_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        return (
            cls.pending_for_payment(
                payment_id,
            )
            .select_for_update()
        )

    @classmethod
    def terminal_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        return (
            cls.terminal_for_payment(
                payment_id,
            )
            .select_for_update()
        )

    @classmethod
    def latest_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Lock the latest attempt.

        If Payment synchronization is involved, the caller should already
        hold the Payment aggregate lock.
        """

        return cls.for_payment_for_update(
            payment_id,
        ).first()

    # ================================
    # GLOBAL STATUS QUERIES
    # ================================

    @classmethod
    def pending_all(
        cls,
    ) -> QuerySet[PaymentAttempt]:
        return cls.queryset().filter(
            status=PaymentAttemptStatus.PENDING,
        )

    @classmethod
    def successful_all(
        cls,
    ) -> QuerySet[PaymentAttempt]:
        return cls.queryset().filter(
            status=PaymentAttemptStatus.SUCCESS,
        )

    @classmethod
    def failed_all(
        cls,
    ) -> QuerySet[PaymentAttempt]:
        return cls.queryset().filter(
            status=PaymentAttemptStatus.FAILED,
        )

    @classmethod
    def timeout_all(
        cls,
    ) -> QuerySet[PaymentAttempt]:
        return cls.queryset().filter(
            status=PaymentAttemptStatus.TIMEOUT,
        )

    @classmethod
    def cancelled_all(
        cls,
    ) -> QuerySet[PaymentAttempt]:
        return cls.queryset().filter(
            status=PaymentAttemptStatus.CANCELLED,
        )

    @classmethod
    def terminal_all(
        cls,
    ) -> QuerySet[PaymentAttempt]:
        return cls.queryset().filter(
            status__in=cls.TERMINAL_STATUSES,
        )

    # ================================
    # WORKER / RECONCILIATION LOCKING
    # ================================

    @classmethod
    def pending_for_update_skip_locked(
        cls,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return pending attempts using SKIP LOCKED.

        Caller owns transaction.atomic().
        """

        return (
            cls.pending_all()
            .select_for_update(
                skip_locked=True,
            )
            .order_by(
                "started_at",
                "attempt_number",
                "id",
            )
        )

    @classmethod
    def terminal_for_update_skip_locked(
        cls,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return terminal attempts using SKIP LOCKED.
        """

        return (
            cls.terminal_all()
            .select_for_update(
                skip_locked=True,
            )
            .order_by(
                "started_at",
                "attempt_number",
                "id",
            )
        )

    # ================================
    # ATTEMPT NUMBERING
    # ================================

    @classmethod
    def last_attempt_number(
        cls,
        payment_id: int,
    ) -> int | None:
        """
        Return the highest attempt number.

        Informational only.

        Do not use this method as a standalone concurrency mechanism.
        """

        return (
            cls.queryset()
            .filter(
                payment_id=payment_id,
            )
            .aggregate(
                maximum=Max(
                    "attempt_number",
                ),
            )
            .get(
                "maximum",
            )
        )

    @classmethod
    def next_attempt_number(
        cls,
        payment_id: int,
    ) -> int:
        """
        Return the next informational attempt number.

        The caller must hold the canonical Payment lock before using this
        number to create an attempt.
        """

        maximum = cls.last_attempt_number(
            payment_id,
        )

        if maximum is None:
            return 1

        return maximum + 1

    # ================================
    # RETRY CHAIN
    # ================================

    @classmethod
    def retries_for(
        cls,
        attempt_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return direct retries of an attempt.
        """

        return (
            cls.queryset()
            .filter(
                retry_of_id=attempt_id,
            )
            .order_by(
                "attempt_number",
                "id",
            )
        )

    @classmethod
    def latest_retry_for(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt | None:
        return (
            cls.retries_for(
                attempt_id,
            )
            .order_by(
                "-attempt_number",
                "-id",
            )
            .first()
        )

    @classmethod
    def retry_count_for(
        cls,
        attempt_id: int,
    ) -> int:
        return cls.retries_for(
            attempt_id,
        ).count()

    @classmethod
    def find_by_retry_source(
        cls,
        *,
        payment_id: int,
        retry_of_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return direct retries of an attempt within one Payment.
        """

        return (
            cls.for_payment(
                payment_id,
            )
            .filter(
                retry_of_id=retry_of_id,
            )
            .order_by(
                "attempt_number",
                "id",
            )
        )

    # ================================
    # CREATION
    # ================================

    @classmethod
    def create(
        cls,
        **kwargs: Any,
    ) -> PaymentAttempt:
        """
        Create one PaymentAttempt.

        IntegrityError intentionally propagates.

        The caller owns:

            - transaction.atomic()
            - Payment locking
            - attempt-number allocation
            - retry policy
            - business validation
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
        attempt: PaymentAttempt,
        *,
        update_fields: list[str] | tuple[str, ...] | None = None,
    ) -> PaymentAttempt:
        """
        Persist an existing PaymentAttempt.

        Structural identity cannot be modified:

            payment
            payment_id
            attempt_number
            retry_of
            retry_of_id

        PaymentAttempt currently has no version field, so this repository
        does not implement optimistic concurrency for the attempt itself.
        """

        if attempt.pk is None:
            raise ValueError(
                "Cannot persist an unsaved PaymentAttempt."
            )

        fields = (
            list(cls.SAFE_UPDATE_FIELDS)
            if update_fields is None
            else list(update_fields)
        )

        if not fields:
            raise ValueError(
                "PaymentAttemptRepository.save() requires "
                "at least one update field."
            )

        forbidden = cls.STRUCTURAL_FIELDS.intersection(
            fields,
        )

        if forbidden:
            raise ValueError(
                "PaymentAttempt structural identity fields cannot "
                "be modified through PaymentAttemptRepository.save(): "
                + ", ".join(
                    sorted(forbidden),
                )
            )

        unsupported = set(fields).difference(
            cls.SAFE_UPDATE_FIELDS,
        )

        if unsupported:
            raise ValueError(
                "Unsupported PaymentAttempt update fields: "
                + ", ".join(
                    sorted(unsupported),
                )
            )

        attempt.save(
            update_fields=fields,
        )

        return attempt

    # ================================
    # STATE PERSISTENCE
    # ================================

    @classmethod
    def save_state(
        cls,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:
        """
        Persist lifecycle state and gateway execution metadata.

        State legality belongs to the domain model.
        """

        return cls.save(
            attempt,
            update_fields=cls.STATE_UPDATE_FIELDS,
        )

    @classmethod
    def save_gateway_identity(
        cls,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:
        """
        Persist gateway identifiers and normalized gateway response data.
        """

        return cls.save(
            attempt,
            update_fields=(
                "authority_id",
                "gateway_reference",
                "gateway_transaction_id",
                "response_code",
                "gateway_message",
            ),
        )

    @classmethod
    def save_failure(
        cls,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:
        """
        Persist a failed attempt and its gateway evidence.
        """

        return cls.save(
            attempt,
            update_fields=(
                "status",
                "response_code",
                "gateway_message",
                "failure_reason",
                "finished_at",
                "latency_ms",
            ),
        )

    @classmethod
    def save_success(
        cls,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:
        """
        Persist a successful attempt and gateway identity.
        """

        return cls.save(
            attempt,
            update_fields=(
                "status",
                "authority_id",
                "gateway_reference",
                "gateway_transaction_id",
                "response_code",
                "gateway_message",
                "failure_reason",
                "finished_at",
                "latency_ms",
            ),
        )

    # ================================
    # REQUEST CONTEXT
    # ================================

    @classmethod
    def save_request_context(
        cls,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:
        """
        Persist non-financial request context.
        """

        return cls.save(
            attempt,
            update_fields=(
                "ip_address",
                "user_agent",
                "meta",
            ),
        )

    # ================================
    # TIMING
    # ================================

    @classmethod
    def save_timing(
        cls,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:
        """
        Persist execution timing.
        """

        return cls.save(
            attempt,
            update_fields=(
                "finished_at",
                "latency_ms",
            ),
        )

    # ================================
    # CONDITIONAL TERMINAL TRANSITION
    # ================================

    @classmethod
    def mark_terminal_if_pending(
        cls,
        *,
        attempt_id: int,
        status: str,
        finished_at=None,
        latency_ms: int | None = None,
    ) -> bool:
        """
        Atomically transition:

            PENDING -> terminal status

        Returns True when exactly one row changed.

        Returns False when the attempt is no longer pending.

        This is a low-level persistence primitive.

        It does not:

            - perform gateway reconciliation
            - validate business policy
            - mutate Payment
            - publish events
        """

        if status not in cls.TERMINAL_STATUSES:
            raise ValueError(
                "mark_terminal_if_pending() requires a terminal "
                f"status, got: {status!r}"
            )

        if latency_ms is not None and latency_ms < 0:
            raise ValueError(
                "latency_ms cannot be negative."
            )

        if finished_at is None:
            finished_at = timezone.now()

        update_kwargs: dict[str, Any] = {
            "status": status,
            "finished_at": finished_at,
        }

        if latency_ms is not None:
            update_kwargs["latency_ms"] = latency_ms

        rows_affected = (
            cls.model.objects
            .filter(
                pk=attempt_id,
                status=PaymentAttemptStatus.PENDING,
            )
            .update(
                **update_kwargs,
            )
        )

        return rows_affected == 1

    # ================================
    # STALE PENDING / RECONCILIATION
    # ================================

    @classmethod
    def stale_pending(
        cls,
        *,
        started_before,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return pending attempts older than a timestamp.
        Candidate selection only.
        """

        return (
            cls.pending_all()
            .filter(
                started_at__lt=started_before,
            )
            .order_by(
                "started_at",
                "attempt_number",
                "id",
            )
        )

    @classmethod
    def stale_pending_for_update_skip_locked(
        cls,
        *,
        started_before,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return stale pending attempts with SKIP LOCKED.
        Intended for reconciliation workers.
        Caller owns transaction.atomic().
        """

        return (
            cls.stale_pending(
                started_before=started_before,
            )
            .select_for_update(
                skip_locked=True,
            )
        )

    # ================================
    # REPRESENTATION
    # ================================

    def __repr__(self) -> str:
        return (
            f"<PaymentAttemptRepository "
            f"model={self.model.__name__}>"
        )