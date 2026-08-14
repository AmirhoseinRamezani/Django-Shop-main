# core/payment/repositories/payment_attempt_repository.py

from __future__ import annotations

from typing import Any, ClassVar

from django.db import IntegrityError
from django.db.models import Max, QuerySet
from django.utils import timezone

from payment.enums import PaymentAttemptStatus
from payment.models import PaymentAttempt
from payment.repositories.base import BaseRepository

class PaymentAttemptRepository(BaseRepository):
    """
    Persistence repository for PaymentAttempt.

    Responsibilities:
        - PaymentAttempt persistence
        - read/query composition
        - row locking
        - gateway identity lookup
        - retry-chain lookup
        - state-specific persistence
        - low-level conditional updates

    Explicitly outside this repository:
        - transaction ownership
        - payment business policy
        - retry eligibility
        - gateway HTTP calls
        - state-transition decisions
        - attempt-number allocation policy
        - financial calculations
        - currency conversion
        - FX
        - Money value objects

    V1 MONEY CONTRACT
    -----------------

    PaymentAttempt does not perform any monetary calculation.

    Payment amount/currency belongs to the Payment aggregate.

    V1 supports Iranian Rial only. No currency conversion or FX
    concerns belong in this repository.
    """

    model: ClassVar[type[PaymentAttempt]] = PaymentAttempt

    # ------------------------------------
    # STATUS GROUPS
    # ------------------------------------

    _TERMINAL_STATUSES: ClassVar[tuple[str, ...]] = (
        PaymentAttemptStatus.SUCCESS,
        PaymentAttemptStatus.FAILED,
        PaymentAttemptStatus.TIMEOUT,
        PaymentAttemptStatus.CANCELLED,
    )

    _ACTIVE_STATUSES: ClassVar[tuple[str, ...]] = (
        PaymentAttemptStatus.PENDING,
    )

    # ------------------------------------
    # PROTECTED / SAFE FIELDS
    # ------------------------------------

    _STRUCTURAL_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "payment",
            "payment_id",
            "attempt_number",
            "retry_of",
            "retry_of_id",
        }
    )

    _SAFE_UPDATE_FIELDS: ClassVar[tuple[str, ...]] = (
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

    _STATE_UPDATE_FIELDS: ClassVar[tuple[str, ...]] = (
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

    # ------------------------------------
    # BASE QUERYSET
    # ------------------------------------

    @classmethod
    def queryset(cls) -> QuerySet[PaymentAttempt]:
        """
        Return the base lazy QuerySet.

        No:
            - transaction
            - locking
            - business filtering
        """
        return cls.model.objects.all()

    # ------------------------------------
    # BASIC READ
    # ------------------------------------

    @classmethod
    def get(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt:
        """
        Retrieve one PaymentAttempt by primary key.

        Raises:
            PaymentAttempt.DoesNotExist
        """
        return cls.queryset().get(pk=attempt_id)

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
            .filter(pk=attempt_id)
            .first()
        )

    # ------------------------------------
    # PAYMENT-SCOPED QUERIES
    # ------------------------------------

    @classmethod
    def for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return all attempts belonging to one Payment.

        Deterministic ordering:
            newest attempt number first
            newest database identity first
        """
        return (
            cls.queryset()
            .filter(payment_id=payment_id)
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
        Return the number of attempts belonging to a Payment.

        Informational only.

        This method MUST NOT be used to allocate attempt_number.
        """
        return cls.for_payment(payment_id).count()

    @classmethod
    def latest_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Return the latest attempt for a Payment.
        """
        return cls.for_payment(payment_id).first()

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
            .filter(payment_id=payment_id)
            .order_by(
                "attempt_number",
                "id",
            )
            .first()
        )

    # ------------------------------------
    # STATUS QUERIES
    # ------------------------------------

    @classmethod
    def _for_status(
        cls,
        payment_id: int,
        status: str,
    ) -> QuerySet[PaymentAttempt]:
        """
        Compose a Payment-scoped status query.
        """
        return (
            cls.for_payment(payment_id)
            .filter(status=status)
        )

    @classmethod
    def pending_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return pending attempts for a Payment.
        """
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.PENDING,
        )

    @classmethod
    def successful_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return successful attempts for a Payment.
        """
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.SUCCESS,
        )

    @classmethod
    def failed_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return failed attempts for a Payment.
        """
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.FAILED,
        )

    @classmethod
    def timeout_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return timeout attempts for a Payment.
        """
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.TIMEOUT,
        )

    @classmethod
    def cancelled_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return cancelled attempts for a Payment.
        """
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.CANCELLED,
        )

    @classmethod
    def terminal_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return terminal attempts for a Payment.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                status__in=cls._TERMINAL_STATUSES,
            )
        )

    @classmethod
    def active_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return currently active attempts.

        Currently only PENDING is considered active.

        This query does not decide whether creating another attempt
        is allowed.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                status__in=cls._ACTIVE_STATUSES,
            )
        )

    # ------------------------------------
    # LATEST STATUS SHORTCUTS
    # ------------------------------------

    @classmethod
    def latest_pending_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        return cls.pending_for_payment(payment_id).first()

    @classmethod
    def latest_successful_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        return cls.successful_for_payment(payment_id).first()

    @classmethod
    def latest_failed_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        return cls.failed_for_payment(payment_id).first()

    @classmethod
    def latest_timeout_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        return cls.timeout_for_payment(payment_id).first()

    @classmethod
    def latest_cancelled_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        return cls.cancelled_for_payment(payment_id).first()

    # ------------------------------------
    # EXISTENCE QUERIES
    # ------------------------------------

    @classmethod
    def exists_for_payment(
        cls,
        payment_id: int,
    ) -> bool:
        return (
            cls.queryset()
            .filter(payment_id=payment_id)
            .exists()
        )

    @classmethod
    def exists_pending(
        cls,
        payment_id: int,
    ) -> bool:
        """
        Convenience query only.

        NOT a concurrency guarantee.
        """
        return cls.pending_for_payment(payment_id).exists()

    @classmethod
    def exists_successful(
        cls,
        payment_id: int,
    ) -> bool:
        return cls.successful_for_payment(payment_id).exists()

    @classmethod
    def exists_terminal(
        cls,
        payment_id: int,
    ) -> bool:
        return (
            cls.for_payment(payment_id)
            .filter(
                status__in=cls._TERMINAL_STATUSES,
            )
            .exists()
        )

    @classmethod
    def has_successful_attempt(
        cls,
        payment_id: int,
    ) -> bool:
        return cls.exists_successful(payment_id)

    @classmethod
    def has_active_attempt(
        cls,
        payment_id: int,
    ) -> bool:
        return cls.exists_pending(payment_id)

    # ------------------------------------
    # GATEWAY IDENTITY NORMALIZATION
    # ------------------------------------

    @staticmethod
    def _normalize_identity(
        value: str | None,
    ) -> str:
        """
        Normalize gateway identity for persistence lookup.

        Deliberately only strips surrounding whitespace.

        The repository does NOT:
            - lowercase identifiers
            - remove leading zeros
            - reinterpret gateway identifiers
            - change gateway formats
        """
        return str(value or "").strip()

    # ------------------------------------
    # GATEWAY IDENTITY LOOKUPS
    # ------------------------------------

    @classmethod
    def find_by_authority(
        cls,
        *,
        payment_id: int,
        authority_id: str,
    ) -> PaymentAttempt | None:
        authority = cls._normalize_identity(authority_id)

        if not authority:
            return None

        return (
            cls.for_payment(payment_id)
            .filter(authority_id=authority)
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
            gateway_reference
        )

        if not reference:
            return None

        return (
            cls.for_payment(payment_id)
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
            gateway_transaction_id
        )

        if not transaction_id:
            return None

        return (
            cls.for_payment(payment_id)
            .filter(
                gateway_transaction_id=transaction_id,
            )
            .first()
        )

    # ------------------------------------
    # GATEWAY IDENTITY LOOKUPS + LOCK
    # ------------------------------------

    @classmethod
    def find_by_authority_for_update(
        cls,
        *,
        payment_id: int,
        authority_id: str,
    ) -> PaymentAttempt | None:
        """
        Find and lock an attempt by authority.

        Only the PaymentAttempt row is locked.

        The owning Payment row is NOT locked.

        The caller owns transaction.atomic().
        """
        authority = cls._normalize_identity(authority_id)

        if not authority:
            return None

        return (
            cls.for_payment(payment_id)
            .filter(authority_id=authority)
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
            gateway_reference
        )

        if not reference:
            return None

        return (
            cls.for_payment(payment_id)
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
            gateway_transaction_id
        )

        if not transaction_id:
            return None

        return (
            cls.for_payment(payment_id)
            .filter(
                gateway_transaction_id=transaction_id,
            )
            .select_for_update()
            .first()
        )

    # ------------------------------------
    # PRIMARY KEY LOCKING
    # ------------------------------------

    @classmethod
    def get_for_update(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt:
        """
        Retrieve and lock one PaymentAttempt.

        Caller MUST own transaction.atomic().
        """
        return (
            cls.queryset()
            .select_for_update()
            .get(pk=attempt_id)
        )

    @classmethod
    def get_for_update_nowait(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt:
        """
        Retrieve and lock one PaymentAttempt using NOWAIT.

        Database lock behavior remains visible to the application layer.
        """
        return (
            cls.queryset()
            .select_for_update(nowait=True)
            .get(pk=attempt_id)
        )

    @classmethod
    def find_for_update(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt | None:
        """
        Retrieve and lock an attempt if it exists.
        """
        return (
            cls.queryset()
            .filter(pk=attempt_id)
            .select_for_update()
            .first()
        )

    # ------------------------------------
    # PAYMENT-SCOPED LOCKING
    # ------------------------------------

    @classmethod
    def for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return all attempts for a Payment with row-level locks.

        The Payment row itself is NOT locked.
        """
        return (
            cls.for_payment(payment_id)
            .select_for_update()
            .order_by(
                "-attempt_number",
                "-id",
            )
        )

    @classmethod
    def pending_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return pending attempts with row-level locks.
        """
        return (
            cls.pending_for_payment(payment_id)
            .select_for_update()
            .order_by(
                "-attempt_number",
                "-id",
            )
        )

    @classmethod
    def terminal_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return terminal attempts with row-level locks.
        """
        return (
            cls.terminal_for_payment(payment_id)
            .select_for_update()
            .order_by(
                "-attempt_number",
                "-id",
            )
        )

    @classmethod
    def latest_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Retrieve and lock the latest attempt.

        If synchronization with Payment is required, the caller should
        already hold the Payment aggregate lock according to the
        application's canonical lock order.
        """
        return cls.for_payment_for_update(payment_id).first()

    # ------------------------------------
    # WORKER / RECONCILIATION LOCKING
    # ------------------------------------

    @classmethod
    def pending_for_update_skip_locked(
        cls,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return pending attempts using FOR UPDATE SKIP LOCKED.

        Intended for worker/reconciliation workflows.

        Caller owns transaction.atomic().
        """
        return (
            cls.pending_all()
            .select_for_update(skip_locked=True)
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
        Return terminal attempts using FOR UPDATE SKIP LOCKED.

        Intended for asynchronous reconciliation/reporting workflows.
        """
        return (
            cls.terminal_all()
            .select_for_update(skip_locked=True)
            .order_by(
                "started_at",
                "attempt_number",
                "id",
            )
        )

    # ------------------------------------
    # GLOBAL STATUS QUERIES
    # ------------------------------------

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
        return (
            cls.queryset()
            .filter(
                status__in=cls._TERMINAL_STATUSES,
            )
        )

    # ------------------------------------
    # ATTEMPT NUMBERING
    # ------------------------------------

    @classmethod
    def last_attempt_number(
        cls,
        payment_id: int,
    ) -> int | None:
        """
        Return the highest existing attempt number.

        Informational only.

        MUST NOT be used directly as a concurrency-safe allocator.
        """
        return (
            cls.queryset()
            .filter(payment_id=payment_id)
            .aggregate(
                maximum=Max("attempt_number"),
            )
            .get("maximum")
        )

    @classmethod
    def next_attempt_number(
        cls,
        payment_id: int,
    ) -> int:
        """
        Return the next informational attempt number.

        IMPORTANT:

        This is NOT concurrency-safe.

        The application service must hold the canonical Payment lock
        before allocating a new attempt number.

        Database uniqueness constraints remain authoritative.
        """
        maximum = cls.last_attempt_number(payment_id)

        if maximum is None:
            return 1

        return maximum + 1

    # ------------------------------------
    # RETRY CHAIN
    # ------------------------------------

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
        """
        Return the latest direct retry.
        """
        return (
            cls.retries_for(attempt_id)
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
        """
        Return the number of direct retries.

        Informational only.
        """
        return cls.retries_for(attempt_id).count()

    @classmethod
    def find_by_retry_source(
        cls,
        *,
        payment_id: int,
        retry_of_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return direct retries of a source attempt within one Payment.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                retry_of_id=retry_of_id,
            )
            .order_by(
                "attempt_number",
                "id",
            )
        )

    # ------------------------------------
    # CREATION
    # ------------------------------------

    @classmethod
    def create(
        cls,
        **kwargs: Any,
    ) -> PaymentAttempt:
        """
        Create and persist a PaymentAttempt.

        The caller owns:
            - transaction.atomic()
            - Payment locking
            - attempt-number allocation
            - retry policy
            - business validation
            - gateway workflow

        IntegrityError intentionally propagates.
        """
        return cls.model.objects.create(**kwargs)

    @classmethod
    def create_safely(
        cls,
        **kwargs: Any,
    ) -> PaymentAttempt:
        """
        Explicit semantic alias for concurrency-sensitive creation.

        IntegrityError intentionally propagates to the application layer.
        """
        try:
            return cls.create(**kwargs)
        except IntegrityError:
            raise

    # ------------------------------------
    # PERSISTENCE
    # ------------------------------------

    @classmethod
    def save(
        cls,
        attempt: PaymentAttempt,
        *,
        update_fields: list[str] | tuple[str, ...] | None = None,
    ) -> PaymentAttempt:
        """
        Persist an existing PaymentAttempt.

        Structural identity fields cannot be changed through this
        repository method:

            payment
            payment_id
            attempt_number
            retry_of
            retry_of_id

        The repository does not implement optimistic locking because
        PaymentAttempt currently has no version field.

        The caller owns transaction.atomic() where required.
        """
        if attempt.pk is None:
            raise ValueError(
                "Cannot persist an unsaved PaymentAttempt "
                "through PaymentAttemptRepository.save()."
            )

        if update_fields is None:
            fields = list(cls._SAFE_UPDATE_FIELDS)
        else:
            fields = list(update_fields)

        forbidden = cls._STRUCTURAL_FIELDS.intersection(fields)

        if forbidden:
            forbidden_fields = ", ".join(sorted(forbidden))

            raise ValueError(
                "PaymentAttempt structural identity fields cannot "
                "be modified through PaymentAttemptRepository.save(): "
                f"{forbidden_fields}"
            )

        unsupported = set(fields).difference(
            cls._SAFE_UPDATE_FIELDS
        )

        if unsupported:
            unsupported_fields = ", ".join(sorted(unsupported))

            raise ValueError(
                "Unsupported PaymentAttempt update fields: "
                f"{unsupported_fields}"
            )

        attempt.save(update_fields=fields)

        return attempt

    # ------------------------------------
    # STATE PERSISTENCE
    # ------------------------------------

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
            update_fields=cls._STATE_UPDATE_FIELDS,
        )

    @classmethod
    def save_gateway_identity(
        cls,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:
        """
        Persist gateway identity and normalized gateway response data.
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
        Persist failure state and failure evidence.
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
        Persist successful attempt state and gateway identities.
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

    # ------------------------------------
    # REQUEST CONTEXT PERSISTENCE
    # ------------------------------------

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

    # ------------------------------------
    # TIMING PERSISTENCE
    # ------------------------------------

    @classmethod
    def save_timing(
        cls,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:
        """
        Persist execution timing information.
        """
        return cls.save(
            attempt,
            update_fields=(
                "finished_at",
                "latency_ms",
            ),
        )

    # ------------------------------------
    # CONDITIONAL PERSISTENCE
    # ------------------------------------

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
        Atomically transition PENDING -> terminal status.

        This is a low-level persistence primitive.

        It does NOT:
            - validate business eligibility
            - perform gateway reconciliation
            - mutate Payment
            - decide refund state
            - dispatch events

        Returns:
            True:
                exactly one row was changed.

            False:
                the attempt was no longer pending.
        """
        if status not in cls._TERMINAL_STATUSES:
            raise ValueError(
                "mark_terminal_if_pending() requires a terminal "
                f"status, got: {status!r}"
            )

        if finished_at is None:
            finished_at = timezone.now()

        update_kwargs: dict[str, Any] = {
            "status": status,
            "finished_at": finished_at,
        }

        if latency_ms is not None:
            if latency_ms < 0:
                raise ValueError(
                    "latency_ms cannot be negative."
                )

            update_kwargs["latency_ms"] = latency_ms

        rows_affected = (
            cls.model.objects
            .filter(
                pk=attempt_id,
                status=PaymentAttemptStatus.PENDING,
            )
            .update(**update_kwargs)
        )

        return rows_affected == 1

    # ------------------------------------
    # STALE PENDING / RECONCILIATION
    # ------------------------------------

    @classmethod
    def stale_pending(
        cls,
        *,
        started_before,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return pending attempts older than the supplied timestamp.

        This is candidate selection only.
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
        Return stale pending attempts using:

            SELECT ... FOR UPDATE SKIP LOCKED

        Intended for reconciliation workers.

        Caller owns transaction.atomic().
        """
        return (
            cls.stale_pending(
                started_before=started_before,
            )
            .select_for_update(skip_locked=True)
        )

    # ------------------------------------
    # REPRESENTATION
    # ------------------------------------

    def __repr__(self) -> str:
        return (
            f"<PaymentAttemptRepository "
            f"model={self.model.__name__}>"
        )