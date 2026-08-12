# core/payment/repositories/payment_attempt_repository.py

from __future__ import annotations

from typing import Any, ClassVar

from django.db.models import Max, QuerySet

from payment.enums import PaymentAttemptStatus
from payment.models import PaymentAttempt
from payment.repositories.base import BaseRepository


class PaymentAttemptRepository(BaseRepository):
    """
    Persistence boundary for PaymentAttempt.

    This repository is intentionally persistence-focused.

    Responsibilities
    ----------------
    - Build PaymentAttempt QuerySets.
    - Read PaymentAttempt records.
    - Query attempts within a Payment aggregate.
    - Query gateway identities within a Payment scope.
    - Acquire explicit PaymentAttempt row locks.
    - Persist PaymentAttempt instances.
    - Calculate the next attempt number.

    Non-responsibilities
    --------------------
    - Payment state transitions.
    - PaymentAttempt state transitions.
    - Retry policy.
    - Authorization.
    - Gateway communication.
    - Gateway verification.
    - Callback/webhook validation.
    - Order mutation.
    - Event dispatching.
    - Transaction management.

    Transaction ownership
    ---------------------
    Transaction boundaries belong to the Application Service layer.

    This repository never opens transaction.atomic().

    Concurrency
    -----------
    Attempt numbers belong to the Payment aggregate.

    For concurrent attempt creation, the caller must:

        1. Enter transaction.atomic().
        2. Lock the owning Payment row.
        3. Call next_attempt_number().
        4. Create the PaymentAttempt.
        5. Rely on the database unique constraint on
           (payment, attempt_number) as the final integrity guard.

    Canonical lock ordering:

        Payment
            ↓
        PaymentAttempt

    This repository never acquires a Payment lock implicitly.

    Identity semantics
    ------------------
    Gateway identities are currently stored on PaymentAttempt:

        authority_id
        gateway_reference
        gateway_transaction_id

    The current schema does not declare these fields globally unique.

    Therefore identity lookups are Payment-scoped.
    """

    model: ClassVar[type[PaymentAttempt]] = PaymentAttempt

    _TERMINAL_STATUSES: ClassVar[tuple[str, ...]] = (
        PaymentAttemptStatus.SUCCESS,
        PaymentAttemptStatus.FAILED,
        PaymentAttemptStatus.TIMEOUT,
        PaymentAttemptStatus.CANCELLED,
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

    # --------------------------------
    # QuerySet
    # --------------------------------

    @classmethod
    def queryset(cls) -> QuerySet[PaymentAttempt]:
        """
        Return the base PaymentAttempt QuerySet.

        The QuerySet remains lazy.

        No transaction is opened and no row is locked.
        """
        return cls.model.objects.all()

    # --------------------------------
    # Read
    # --------------------------------

    @classmethod
    def get(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt:
        """
        Retrieve a PaymentAttempt by primary key.

        Raises:
            PaymentAttempt.DoesNotExist:
                If the attempt does not exist.
        """
        return cls.queryset().get(pk=attempt_id)

    @classmethod
    def find(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt | None:
        """
        Retrieve a PaymentAttempt by primary key.

        Returns:
            PaymentAttempt | None:
        """
        return (
            cls.queryset()
            .filter(pk=attempt_id)
            .first()
        )

    # --------------------------------
    # Payment Scope
    # --------------------------------

    @classmethod
    def for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return attempts belonging to a Payment.

        Ordering is deterministic:

            -attempt_number
            -id
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
    def latest_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """Return the latest attempt for a Payment."""
        return cls.for_payment(payment_id).first()

    @classmethod
    def count_for_payment(
        cls,
        payment_id: int,
    ) -> int:
        """
        Return the number of attempts belonging to a Payment.

        Informational only.

        This method must never be used for attempt-number allocation.
        """
        return cls.for_payment(payment_id).count()

    # --------------------------------
    # State Queries
    # --------------------------------

    @classmethod
    def _for_status(
        cls,
        payment_id: int,
        status: str,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return attempts for a Payment filtered by status.

        This is an internal query composition helper.
        """
        return cls.for_payment(payment_id).filter(status=status)

    @classmethod
    def pending_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """Return pending attempts for a Payment."""
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.PENDING,
        )

    @classmethod
    def successful_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """Return successful attempts for a Payment."""
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.SUCCESS,
        )

    @classmethod
    def failed_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """Return failed attempts for a Payment."""
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.FAILED,
        )

    @classmethod
    def timeout_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """Return timed-out attempts for a Payment."""
        return cls._for_status(
            payment_id,
            PaymentAttemptStatus.TIMEOUT,
        )

    @classmethod
    def cancelled_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """Return cancelled attempts for a Payment."""
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

        Terminal states:

            SUCCESS
            FAILED
            TIMEOUT
            CANCELLED
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                status__in=cls._TERMINAL_STATUSES,
            )
        )

    # --------------------------------
    # State Shortcuts
    # --------------------------------

    @classmethod
    def latest_pending_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """Return the latest pending attempt."""
        return cls.pending_for_payment(payment_id).first()

    @classmethod
    def latest_successful_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """Return the latest successful attempt."""
        return cls.successful_for_payment(payment_id).first()

    @classmethod
    def latest_failed_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """Return the latest failed attempt."""
        return cls.failed_for_payment(payment_id).first()

    @classmethod
    def latest_timeout_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """Return the latest timed-out attempt."""
        return cls.timeout_for_payment(payment_id).first()

    @classmethod
    def latest_cancelled_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """Return the latest cancelled attempt."""
        return cls.cancelled_for_payment(payment_id).first()

    # --------------------------------
    # Existence
    # --------------------------------

    @classmethod
    def exists_pending(
        cls,
        payment_id: int,
    ) -> bool:
        """Return whether a pending attempt exists."""
        return cls.pending_for_payment(payment_id).exists()

    @classmethod
    def exists_successful(
        cls,
        payment_id: int,
    ) -> bool:
        """Return whether a successful attempt exists."""
        return cls.successful_for_payment(payment_id).exists()

    @classmethod
    def exists_terminal(
        cls,
        payment_id: int,
    ) -> bool:
        """Return whether at least one terminal attempt exists."""
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
        """
        Return whether the Payment has a successful attempt.
        Alias kept intentionally explicit for aggregate-oriented callers.
        """
        return cls.exists_successful(payment_id)

    @classmethod
    def has_active_attempt(
        cls,
        payment_id: int,
    ) -> bool:
        """
        Return whether the Payment has an active attempt.
        Currently PENDING is the only active state.
        """
        return cls.exists_pending(payment_id)

    # --------------------------------
    # Gateway Identity
    # --------------------------------

    @staticmethod
    def _normalize_identity(
        value: str,
    ) -> str:
        """
        Normalize an external gateway identity for lookup.
        Repository normalization is intentionally limited to trimming
        surrounding whitespace.
        The repository does not mutate the domain entity.
        """
        return str(value or "").strip()

    @classmethod
    def find_by_authority(
        cls,
        *,
        payment_id: int,
        authority_id: str,
    ) -> PaymentAttempt | None:
        """Find an attempt by authority within a Payment."""
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
        """Find an attempt by gateway reference within a Payment."""
        reference = cls._normalize_identity(gateway_reference)

        if not reference:
            return None

        return (
            cls.for_payment(payment_id)
            .filter(gateway_reference=reference)
            .first()
        )

    @classmethod
    def find_by_transaction_id(
        cls,
        *,
        payment_id: int,
        gateway_transaction_id: str,
    ) -> PaymentAttempt | None:
        """Find an attempt by gateway transaction ID within a Payment."""
        transaction_id = cls._normalize_identity(
            gateway_transaction_id,
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

    # --------------------------------
    # Gateway Identity + Lock
    # --------------------------------

    @classmethod
    def find_by_authority_for_update(
        cls,
        *,
        payment_id: int,
        authority_id: str,
    ) -> PaymentAttempt | None:
        """
        Find and lock an attempt by authority.
        The caller owns the transaction.
        Only the matching PaymentAttempt row is locked.
        The owning Payment row is not locked here.
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
        """
        Find and lock an attempt by gateway reference.
        The caller owns the transaction.
        """
        reference = cls._normalize_identity(gateway_reference)

        if not reference:
            return None

        return (
            cls.for_payment(payment_id)
            .filter(gateway_reference=reference)
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
        """
        Find and lock an attempt by gateway transaction ID.
        The caller owns the transaction.
        """
        transaction_id = cls._normalize_identity(
            gateway_transaction_id,
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

    # --------------------------------
    # Explicit Row Locking
    # --------------------------------

    @classmethod
    def get_for_update(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt:
        """
        Retrieve and lock one PaymentAttempt.
        The caller MUST execute this inside transaction.atomic().
        """
        return (
            cls.queryset()
            .select_for_update()
            .get(pk=attempt_id)
        )

    @classmethod
    def find_for_update(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt | None:
        """
        Retrieve and lock an attempt if it exists.
        The caller MUST execute this inside transaction.atomic().
        """
        return (
            cls.queryset()
            .filter(pk=attempt_id)
            .select_for_update()
            .first()
        )

    @classmethod
    def for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return a locking QuerySet for all attempts of a Payment.
        The QuerySet remains lazy.
        This method locks PaymentAttempt rows only.
        It does not lock the owning Payment row.
        """
        return (
            cls.for_payment(payment_id)
            .select_for_update()
        )

    @classmethod
    def latest_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Return and lock the latest attempt.
        If Payment and PaymentAttempt synchronization is required,
        the caller must already hold the Payment lock.
        """
        return (
            cls.for_payment_for_update(payment_id)
            .first()
        )

    @classmethod
    def pending_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return pending attempts as a locking QuerySet.

        The caller owns the transaction.
        """
        return (
            cls.pending_for_payment(payment_id)
            .select_for_update()
        )

    # --------------------------------
    # Attempt Numbering
    # --------------------------------

    @classmethod
    def last_attempt_number(
        cls,
        payment_id: int,
    ) -> int | None:
        """
        Return the highest attempt number for a Payment.
        Returns None when the Payment has no attempts.
        Informational only.
        This method must not be used alone for concurrent allocation.
        """
        return (
            cls.for_payment(payment_id)
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
        Calculate the next attempt number for a Payment.

        Concurrency contract
        --------------------
        This method does NOT lock the Payment.

        For concurrent attempt creation, the caller MUST:
            1. Enter transaction.atomic().
            2. Lock the owning Payment row.
            3. Call this method.
            4. Create the PaymentAttempt.
            5. Rely on the database UNIQUE(payment, attempt_number)
               constraint as the final integrity guard.

        The Payment row is the serialization point.

        Important
        ---------
        MAX(attempt_number) + 1 is safe against concurrent allocation
        only when all writers follow the Payment-lock protocol.

        It does not permanently reserve numbers after historical
        PaymentAttempt rows are deleted.
        """
        maximum = (
            cls.for_payment(payment_id)
            .aggregate(
                maximum=Max("attempt_number"),
            )
            .get("maximum")
        )

        if maximum is None:
            return 1

        return int(maximum) + 1

    # --------------------------------
    # Persistence
    # --------------------------------

    @classmethod
    def create(
        cls,
        **kwargs: Any,
    ) -> PaymentAttempt:
        """
        Persist a new PaymentAttempt.

        The caller is responsible for:
            - transaction boundaries;
            - Payment locking;
            - attempt number allocation;
            - retry policy;
            - domain correctness.
            
        Database constraints remain authoritative.
        """
        return cls.model.objects.create(**kwargs)

    @classmethod
    def save(
        cls,
        attempt: PaymentAttempt,
        *,
        update_fields: list[str] | tuple[str, ...] | None = None,
    ) -> PaymentAttempt:
        """
        Persist a previously loaded PaymentAttempt.

        The repository does not:

            - perform state transitions;
            - implement retry policy;
            - open transactions;
            - call gateways.

        PaymentAttempt.save() remains responsible for model-level
        validation.
        """
        attempt.save(update_fields=update_fields)

        return attempt

    @classmethod
    def save_state(
        cls,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:
        """
        Persist fields belonging to the PaymentAttempt lifecycle.

        This method does not infer or perform a state transition.
        The domain model must already have been mutated by the caller.
        """
        return cls.save(
            attempt,
            update_fields=cls._STATE_UPDATE_FIELDS,
        )