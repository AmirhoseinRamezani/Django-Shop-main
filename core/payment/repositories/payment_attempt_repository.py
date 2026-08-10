# payment/repositories/payment_attempt_repository.py
from __future__ import annotations

from typing import ClassVar

from django.db.models import Max, QuerySet

from payment.enums import PaymentAttemptStatus
from payment.models import PaymentAttempt
from payment.repositories.base import BaseRepository

class PaymentAttemptRepository(BaseRepository):
    """
    Persistence boundary for PaymentAttempt.
    PaymentAttempt belongs to a Payment aggregate.

    Responsibilities
    ----------------
    - Retrieve PaymentAttempt instances.
    - Compose payment-scoped queries.
    - Query gateway identifiers within their actual database scope.
    - Acquire explicit PaymentAttempt row locks.
    - Persist PaymentAttempt instances.
    - Calculate the next payment-scoped attempt number.

    Non-responsibilities
    --------------------
    - Payment state transitions.
    - Payment aggregate mutation.
    - Gateway communication.
    - Gateway verification.
    - Retry policy.
    - Retry authorization.
    - Callback processing policy.
    - Transaction management.
    - Event dispatching.
    - Order mutation.
    - PaymentAttempt business transitions.

    Transaction ownership
    ---------------------
    This repository never creates transaction.atomic() boundaries.
    The application/service layer owns transactions.

    Lock ordering
    -------------
    When both Payment and PaymentAttempt must be locked, the
    canonical order is:

        Payment
            ↓
        PaymentAttempt

    PaymentAttemptRepository never acquires a Payment lock implicitly.

    Attempt numbering
    -----------------
    attempt_number belongs to the Payment aggregate.
    The Payment row is therefore the serialization point.
    next_attempt_number() is concurrency-safe only when the caller
    already holds a row-level lock on the corresponding Payment
    inside transaction.atomic().
    Database uniqueness remains the final integrity guard through:
        UNIQUE(payment, attempt_number)

    Identity semantics
    ------------------
    authority_id, gateway_reference, and gateway_transaction_id are
    PaymentAttempt identities.

    They are NOT treated as globally unique identities because the
    database does not guarantee global uniqueness for them.

    Any identity lookup that is not database-unique must therefore
    preserve its Payment scope.
    """
    model: ClassVar[type[PaymentAttempt]] = PaymentAttempt
    # ==================================================================
    # Base QuerySet
    # ==================================================================
    @classmethod
    def queryset(cls) -> QuerySet[PaymentAttempt]:
        """
        Return the base PaymentAttempt QuerySet.

        The QuerySet remains lazy.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.model.objects.all()

    # ==================================================================
    # Read
    # ==================================================================

    @classmethod
    def get(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt:
        """
        Retrieve a PaymentAttempt by primary key.

        Args:
            attempt_id:
                PaymentAttempt primary-key value.

        Returns:
            PaymentAttempt

        Raises:
            PaymentAttempt.DoesNotExist:
                If the attempt does not exist.

        Locking:
            None.

        Transaction:
            Not required.
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
        Retrieve a PaymentAttempt by primary key if it exists.

        Returns:
            PaymentAttempt | None

        Locking:
            None.

        Transaction:
            Not required.
        """
        return (
            cls.queryset()
            .filter(
                pk=attempt_id,
            )
            .first()
        )

    # ==================================================================
    # Payment Scope
    # ==================================================================

    @classmethod
    def for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return all attempts belonging to one Payment.

        The QuerySet is lazy.

        Ordering is explicit and deterministic:

            -attempt_number
            -id

        Locking:
            None.

        Transaction:
            Not required.
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
    def latest_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Return the latest attempt for a Payment.

        Ordering is deterministic.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return (
            cls.for_payment(payment_id)
            .first()
        )

    # ==================================================================
    # State Queries
    # ==================================================================

    @classmethod
    def pending_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return pending attempts belonging to a Payment.

        This method performs only persistence-level filtering.

        It does not decide whether a pending attempt may transition
        to another state.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.for_payment(
            payment_id,
        ).filter(
            status=PaymentAttemptStatus.PENDING,
        )

    @classmethod
    def successful_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return successful attempts belonging to a Payment.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.for_payment(
            payment_id,
        ).filter(
            status=PaymentAttemptStatus.SUCCESS,
        )

    @classmethod
    def failed_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return failed attempts belonging to a Payment.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.for_payment(
            payment_id,
        ).filter(
            status=PaymentAttemptStatus.FAILED,
        )

    @classmethod
    def timeout_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return timed-out attempts belonging to a Payment.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.for_payment(
            payment_id,
        ).filter(
            status=PaymentAttemptStatus.TIMEOUT,
        )

    @classmethod
    def cancelled_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return cancelled attempts belonging to a Payment.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.for_payment(
            payment_id,
        ).filter(
            status=PaymentAttemptStatus.CANCELLED,
        )

    # ==================================================================
    # Latest State Queries
    # ==================================================================

    @classmethod
    def latest_successful_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Return the latest successful attempt for a Payment.

        Ordering:
            -attempt_number
            -id

        Locking:
            None.

        Transaction:
            Not required.
        """
        return (
            cls.successful_for_payment(payment_id)
            .first()
        )

    @classmethod
    def latest_failed_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Return the latest failed attempt for a Payment.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return (
            cls.failed_for_payment(payment_id)
            .first()
        )

    @classmethod
    def latest_pending_for_payment(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Return the latest pending attempt for a Payment.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return (
            cls.pending_for_payment(payment_id)
            .first()
        )

    # ==================================================================
    # Gateway Identity
    # ==================================================================

    @classmethod
    def find_by_authority(
        cls,
        *,
        payment_id: int,
        authority_id: str,
    ) -> PaymentAttempt | None:
        """
        Find an attempt by authority within a specific Payment.

        authority_id is NOT globally unique in the current database
        contract.

        Therefore payment_id is mandatory.

        This method intentionally returns None when no matching
        attempt exists.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                authority_id=authority_id,
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
        """
        Find an attempt by gateway reference within a Payment.

        gateway_reference is not treated as globally unique.

        payment_id therefore remains part of the lookup contract.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                gateway_reference=gateway_reference,
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
        """
        Find an attempt by gateway transaction ID within a Payment.

        gateway_transaction_id is not treated as globally unique.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                gateway_transaction_id=gateway_transaction_id,
            )
            .first()
        )

    # ==================================================================
    # Gateway Identity + Lock
    # ==================================================================

    @classmethod
    def find_by_authority_for_update(
        cls,
        *,
        payment_id: int,
        authority_id: str,
    ) -> PaymentAttempt | None:
        """
        Find and lock an attempt by authority within a Payment.

        Concurrency contract
        --------------------
        Caller MUST execute this method inside transaction.atomic().

        Lock ordering
        -------------
        If the workflow also requires the Payment lock:

            Payment
                ↓
            PaymentAttempt

        This method locks only the matching PaymentAttempt row.

        It does NOT lock the Payment row.

        Identity semantics
        ------------------
        authority_id is Payment-scoped because the current database
        schema does not guarantee global uniqueness.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                authority_id=authority_id,
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
        """
        Find and lock an attempt by gateway reference within a Payment.

        Transaction:
            Caller-owned.

        Locking:
            Locks the matching PaymentAttempt row only.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                gateway_reference=gateway_reference,
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
        """
        Find and lock an attempt by gateway transaction ID within
        a Payment.

        Transaction:
            Caller-owned.

        Locking:
            Locks the matching PaymentAttempt row only.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                gateway_transaction_id=gateway_transaction_id,
            )
            .select_for_update()
            .first()
        )

    # ==================================================================
    # Explicit Row Locking
    # ==================================================================

    @classmethod
    def get_for_update(
        cls,
        attempt_id: int,
    ) -> PaymentAttempt:
        """
        Retrieve and row-lock one PaymentAttempt.

        Concurrency contract
        --------------------
        Caller MUST execute this method inside transaction.atomic().

        Locked:
            The requested PaymentAttempt row.

        Not locked:
            Payment row.
            Other PaymentAttempt rows.
            Order rows.

        Lock ordering:
            Payment must be locked before this attempt if both are
            required by the workflow.

        Raises:
            PaymentAttempt.DoesNotExist:
                If the attempt does not exist.
        """
        return (
            cls.queryset()
            .select_for_update()
            .get(
                pk=attempt_id,
            )
        )

    @classmethod
    def latest_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> PaymentAttempt | None:
        """
        Return and lock the latest PaymentAttempt for a Payment.

        The QuerySet is evaluated by first(), so the matching latest
        row is selected and locked.

        Transaction:
            Caller MUST be inside transaction.atomic().

        Locking:
            Locks only the selected PaymentAttempt row.

        Important:
            This method does NOT lock the Payment row.

        If both locks are required, acquire the Payment lock first.
        """
        return (
            cls.for_payment(payment_id)
            .select_for_update()
            .first()
        )

    @classmethod
    def for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[PaymentAttempt]:
        """
        Return all attempts for a Payment as a locked QuerySet.

        The QuerySet remains lazy.

        Transaction:
            Caller MUST evaluate it inside transaction.atomic().

        Locked:
            Matching PaymentAttempt rows.

        Not locked:
            Payment row.

        Lock ordering:
            Payment first, PaymentAttempt second.

        Use this method only when a workflow genuinely needs to inspect
        or mutate multiple attempts under one transaction.
        """
        return (
            cls.for_payment(payment_id)
            .select_for_update()
        )

    # ==================================================================
    # Persistence
    # ==================================================================

    @classmethod
    def create(
        cls,
        **kwargs,
    ) -> PaymentAttempt:
        """
        Persist a new PaymentAttempt.

        The repository does not:
            - generate attempt numbers implicitly;
            - create a Payment;
            - mutate Payment status;
            - apply retry policy;
            - call a gateway;
            - open a transaction.

        The caller must provide a valid attempt_number.

        Database constraints remain the final integrity authority.

        In particular:

            UNIQUE(payment, attempt_number)

        prevents duplicate attempt numbers for the same Payment.

        Database exceptions are intentionally allowed to propagate.
        """
        return cls.model.objects.create(
            **kwargs,
        )

    @classmethod
    def save(
        cls,
        attempt: PaymentAttempt,
        *,
        update_fields: list[str] | tuple[str, ...] | None = None,
    ) -> PaymentAttempt:
        """
        Persist a domain-mutated PaymentAttempt.

        The repository does not:
            - call full_clean();
            - perform state transitions;
            - perform gateway verification;
            - open a transaction;
            - mutate Payment.

        Transaction:
            Caller-owned.

        Database exceptions:
            Allowed to propagate unchanged.
        """
        attempt.save(
            update_fields=update_fields,
        )

        return attempt

    # ==================================================================
    # Existence
    # ==================================================================

    @classmethod
    def exists_pending(
        cls,
        payment_id: int,
    ) -> bool:
        """
        Return whether a pending attempt exists for a Payment.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.pending_for_payment(
            payment_id,
        ).exists()

    @classmethod
    def exists_success(
        cls,
        payment_id: int,
    ) -> bool:
        """
        Return whether a successful attempt exists for a Payment.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.successful_for_payment(
            payment_id,
        ).exists()

    # ==================================================================
    # Statistics
    # ==================================================================

    @classmethod
    def count_for_payment(
        cls,
        payment_id: int,
    ) -> int:
        """
        Return the number of attempts belonging to a Payment.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.for_payment(
            payment_id,
        ).count()

    # ==================================================================
    # Attempt Number
    # ==================================================================

    @classmethod
    def next_attempt_number(
        cls,
        payment_id: int,
    ) -> int:
        """
        Calculate the next attempt number for a Payment.

        Concurrency contract
        --------------------
        Caller MUST already hold a row-level lock on the corresponding
        Payment inside transaction.atomic().

        Required workflow:

            with transaction.atomic():
                PaymentRepository.get_for_update(payment_id)

                attempt_number = (
                    PaymentAttemptRepository
                    .next_attempt_number(payment_id)
                )

                PaymentAttemptRepository.create(
                    payment_id=payment_id,
                    attempt_number=attempt_number,
                    ...
                )

        Why Payment is the serialization point
        ----------------------------------------
        attempt_number belongs to the Payment aggregate.

        Locking the Payment row serializes concurrent attempt creation
        workflows for that aggregate.

        This method itself does NOT:

            - open a transaction;
            - lock Payment;
            - lock PaymentAttempt;
            - create PaymentAttempt;
            - commit anything.

        Database integrity
        ------------------
        The database UNIQUE constraint on:

            (payment, attempt_number)

        remains the final integrity guard.

        Historical gaps are preserved.

        Example:

            existing attempts: 1, 2, 4
            next number:       5
        """
        current_max = (
            cls.for_payment(payment_id)
            .aggregate(
                max_attempt_number=Max(
                    "attempt_number",
                ),
            )
            .get(
                "max_attempt_number",
            )
        )

        return (current_max or 0) + 1