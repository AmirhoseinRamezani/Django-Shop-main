# payment/repositories/payment_repository.py
from __future__ import annotations
from typing import ClassVar
from django.db.models import QuerySet

from payment.enums import PaymentStatusType
from payment.models import PaymentModel
from payment.repositories.base import BaseRepository

class PaymentRepository(BaseRepository):
    """
    Persistence boundary for the Payment aggregate.

    Responsibilities
    ----------------
    - Retrieve PaymentModel instances.
    - Compose lazy Payment queries.
    - Acquire explicit Payment row locks.
    - Persist Payment instances.
    - Expose persistence-oriented state queries.

    Non-responsibilities
    --------------------
    - Gateway communication.
    - Payment verification.
    - Retry policy.
    - PaymentAttempt persistence.
    - PaymentAttempt numbering.
    - Order mutation.
    - Business workflow orchestration.
    - Domain state-transition decisions.
    - Event dispatching.
    - Transaction management.

    Transaction ownership
    ---------------------
    This repository does not create transaction boundaries.

    Callers own transaction.atomic().

    Example:

        with transaction.atomic():
            payment = PaymentRepository.get_for_update(payment_id)

            payment.succeed()

            PaymentRepository.save(
                payment,
                update_fields=["status"],
            )

    Locking contract
    ----------------
    get_for_update() uses SELECT ... FOR UPDATE.

    The caller MUST execute it inside transaction.atomic().

    get_for_update() locks the Payment row only.
    PaymentAttempt rows are NOT locked automatically.

    Aggregate boundary
    ------------------
    Payment is the aggregate root.

    PaymentAttempt is a child aggregate component whose persistence
    belongs to PaymentAttemptRepository.

    PaymentRepository must therefore remain Payment-scoped.

    Lock ordering
    -------------
    When a workflow requires both Payment and PaymentAttempt locks,
    callers MUST acquire them in this order:

        Payment
            ↓
        PaymentAttempt

    PaymentRepository never acquires PaymentAttempt locks implicitly.

    Database integrity
    ------------------
    Database constraints remain the final authority for persistence
    integrity. The repository does not replace database constraints
    with application-level existence checks.
    """

    model: ClassVar[type[PaymentModel]] = PaymentModel

    # ------------------------------------------------------------------
    # Base QuerySet
    # ------------------------------------------------------------------

    @classmethod
    def queryset(cls) -> QuerySet[PaymentModel]:
        """
        Return the base Payment QuerySet.

        The QuerySet remains lazy.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.model.objects.all()

    # ------------------------------------------------------------------
    # Required Read
    # ------------------------------------------------------------------

    @classmethod
    def get(
        cls,
        payment_id: int,
    ) -> PaymentModel:
        """
        Retrieve a Payment by primary key.

        Args:
            payment_id:
                Payment primary-key value.

        Returns:
            PaymentModel

        Raises:
            PaymentModel.DoesNotExist:
                If the payment does not exist.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.queryset().get(
            pk=payment_id,
        )

    # ------------------------------------------------------------------
    # Optional Read
    # ------------------------------------------------------------------

    @classmethod
    def find(
        cls,
        payment_id: int,
    ) -> PaymentModel | None:
        """
        Retrieve a Payment by primary key if it exists.

        Returns:
            PaymentModel | None

        Locking:
            None.

        Transaction:
            Not required.

        Exception behavior:
            DoesNotExist is represented as None because this method
            explicitly defines optional lookup semantics.
        """
        return (
            cls.queryset()
            .filter(
                pk=payment_id,
            )
            .first()
        )

    # ------------------------------------------------------------------
    # Order Queries
    # ------------------------------------------------------------------

    @classmethod
    def for_order(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return payments belonging to an order.

        The QuerySet is lazy.

        Locking:
            None.

        Transaction:
            Not required.

        Scope:
            Payment records associated with the supplied Order.
        """
        return cls.queryset().filter(
            order_id=order_id,
        )

    @classmethod
    def pending_for_order(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return pending payments belonging to an order.

        This method performs a persistence query only.

        It does NOT decide whether a pending payment is allowed to
        transition to another state.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.for_order(
            order_id,
        ).filter(
            status=PaymentStatusType.PENDING,
        )

    @classmethod
    def latest_for_order(
        cls,
        order_id: int,
    ) -> PaymentModel | None:
        """
        Return the latest Payment for an order.

        Ordering is explicit and deterministic:

            -created_date
            -id

        Locking:
            None.

        Transaction:
            Not required.
        """
        return (
            cls.for_order(order_id)
            .order_by(
                "-created_date",
                "-id",
            )
            .first()
        )

    @classmethod
    def latest_failed_for_order(
        cls,
        order_id: int,
    ) -> PaymentModel | None:
        """
        Return the latest failed Payment for an order.

        Ordering is explicit and deterministic:

            -updated_date
            -id

        Locking:
            None.

        Transaction:
            Not required.
        """
        return (
            cls.for_order(order_id)
            .filter(
                status=PaymentStatusType.FAILED,
            )
            .order_by(
                "-updated_date",
                "-id",
            )
            .first()
        )

    # ------------------------------------------------------------------
    # State Queries
    # ------------------------------------------------------------------

    @classmethod
    def pending(cls) -> QuerySet[PaymentModel]:
        """
        Return all pending payments.

        The QuerySet is lazy.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.queryset().filter(
            status=PaymentStatusType.PENDING,
        )

    @classmethod
    def successful(cls) -> QuerySet[PaymentModel]:
        """
        Return all successful payments.

        The QuerySet is lazy.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.queryset().filter(
            status=PaymentStatusType.SUCCESS,
        )

    @classmethod
    def failed(cls) -> QuerySet[PaymentModel]:
        """
        Return all failed payments.

        The QuerySet is lazy.

        Locking:
            None.

        Transaction:
            Not required.
        """
        return cls.queryset().filter(
            status=PaymentStatusType.FAILED,
        )

    # ------------------------------------------------------------------
    # Row Locking
    # ------------------------------------------------------------------

    @classmethod
    def get_for_update(
        cls,
        payment_id: int,
    ) -> PaymentModel:
        """
        Retrieve and row-lock one Payment.

        Concurrency contract
        --------------------
        Caller MUST execute this method inside transaction.atomic().

        The method locks exactly the requested Payment row.

        It does NOT automatically lock:
            - PaymentAttempt rows;
            - Order rows;
            - Refund rows;
            - any related records.

        Lock ordering
        -------------
        If the workflow also requires a PaymentAttempt lock:

            Payment
                ↓
            PaymentAttempt

        The Payment row must be locked first.

        Raises:
            PaymentModel.DoesNotExist:
                If the payment does not exist.

        Transaction:
            Owned by the caller.
        """
        return (
            cls.queryset()
            .select_for_update()
            .get(
                pk=payment_id,
            )
        )

    # ------------------------------------------------------------------
    # Order-Scoped Locking
    # ------------------------------------------------------------------

    @classmethod
    def pending_for_order_for_update(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return pending payments for an order with row-level locks.

        The QuerySet is lazy.

        Concurrency contract
        --------------------
        The caller MUST evaluate this QuerySet inside
        transaction.atomic().

        Locked rows:
            Matching pending Payment rows.

        Not locked:
            Order rows.
            PaymentAttempt rows.
            Other Payment rows.

        Lock ordering
        -------------
        If a workflow later requires PaymentAttempt locks, Payment
        locks must be acquired before PaymentAttempt locks.
        """
        return (
            cls.pending_for_order(order_id)
            .select_for_update()
            .order_by(
                "created_date",
                "id",
            )
        )

    # ------------------------------------------------------------------
    # Worker Locking
    # ------------------------------------------------------------------

    @classmethod
    def pending_for_update_skip_locked(
        cls,
    ) -> QuerySet[PaymentModel]:
        """
        Return pending payments using SKIP LOCKED.

        Intended for worker/reconciliation-style workflows where
        already locked Payment rows should be skipped rather than
        blocking the worker.

        The QuerySet is lazy.

        Concurrency contract
        --------------------
        The caller MUST evaluate this QuerySet inside
        transaction.atomic().

        Locked rows:
            Pending Payment rows successfully selected by PostgreSQL.

        Skipped rows:
            Pending Payment rows already locked by another transaction.

        Important:
            This method does not implement a retry policy, verification
            policy, or gateway workflow.
        """
        return (
            cls.pending()
            .select_for_update(
                skip_locked=True,
            )
            .order_by(
                "created_date",
                "id",
            )
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        **kwargs,
    ) -> PaymentModel:
        """
        Persist a new Payment.

        This method delegates creation to Django ORM.

        Responsibilities:
            - Persist Payment data.

        Non-responsibilities:
            - Gateway communication.
            - PaymentAttempt creation.
            - Transaction management.
            - Business validation workflow.
            - Order mutation.

        Transaction:
            Caller-owned.

        Database exceptions:
            Allowed to propagate unchanged.
        """
        return cls.model.objects.create(
            **kwargs,
        )

    @classmethod
    def save(
        cls,
        payment: PaymentModel,
        *,
        update_fields: list[str] | tuple[str, ...] | None = None,
    ) -> PaymentModel:
        """
        Persist a domain-mutated Payment.

        The repository does not:
            - call full_clean();
            - perform domain transitions;
            - inspect current business state;
            - open a transaction;
            - mutate related PaymentAttempt rows.

        Args:
            payment:
                Payment instance to persist.

            update_fields:
                Optional Django update_fields collection.

        Returns:
            The same persisted PaymentModel instance.

        Transaction:
            Caller-owned.

        Database exceptions:
            Allowed to propagate unchanged.
        """
        payment.save(
            update_fields=update_fields,
        )

        return payment