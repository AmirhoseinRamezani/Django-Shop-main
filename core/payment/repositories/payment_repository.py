# core/payment/repositories/payment_repository.py
from __future__ import annotations

from typing import ClassVar

from django.db import IntegrityError
from django.db.models import F, QuerySet

from payment.enums import PaymentStatusType
from payment.exceptions import PaymentConcurrencyError
from payment.models import PaymentModel
from payment.repositories.base import BaseRepository


class PaymentRepository(BaseRepository):
    """
    Persistence boundary for the Payment aggregate.

    ================================
    RESPONSIBILITIES
    ================================

    This repository owns persistence mechanics for PaymentModel:

        - retrieval
        - filtering
        - ordering
        - row-level locking
        - creation
        - optimistic-concurrency persistence
        - persistence-oriented existence checks

    ================================
    NON-RESPONSIBILITIES
    ================================

    This repository MUST NOT own:

        - business policy
        - gateway communication
        - payment verification
        - refund policy
        - PaymentAttempt workflow
        - Order mutation
        - transaction.atomic()
        - Celery
        - event publication
        - webhook handling
        - reconciliation decisions
        - state-transition decisions

    Domain decisions belong to the domain/application layers.

    ================================
    TRANSACTION OWNERSHIP
    ================================

    This repository NEVER creates transaction boundaries.

    Application services own transaction.atomic().

    Example:

        with transaction.atomic():
            payment = PaymentRepository.get_for_update(payment_id)

            payment.succeed()

            PaymentRepository.save(
                payment,
                update_fields=("status",),
            )

    ================================
    LOCKING CONTRACT
    ================================

    get_for_update() and other locking methods require an active
    database transaction.

    The repository does not implicitly create one.

    Payment is the canonical aggregate lock for workflows involving:

        - payment state
        - payment consumption
        - cumulative refunds
        - reconciliation
        - duplicate callback handling

    If a workflow also needs PaymentAttempt locking, the canonical
    lock order is:

        Payment
            ↓
        PaymentAttempt

    PaymentRepository never implicitly locks child records.

    ================================
    OPTIMISTIC CONCURRENCY
    ================================

    PaymentModel.version is an optimistic concurrency token.

    A normal save operation must use compare-and-swap semantics:

        UPDATE payment
        SET ...
            version = version + 1
        WHERE id = ?
          AND version = ?

    Exactly one row must be affected.

    Zero affected rows means that another transaction changed the
    aggregate.

    In that situation PaymentConcurrencyError is raised.

    The repository NEVER silently overwrites a concurrent update.

    ================================
    FINANCIAL IMMUTABILITY
    ================================

    Payment.amount and Payment.currency represent the immutable
    financial snapshot of the Payment lifecycle.

    The repository therefore does not provide a generic workflow
    for changing those fields after creation.

    Creation accepts the financial snapshot.

    Subsequent persistence is intended for mutable aggregate state:

        - status
        - is_consumed
        - is_refunded
        - gateway-related mutable state if introduced later
        - timestamps
        - version

    Financial corrections must be represented by a new domain fact
    rather than silently modifying the original Payment.

    ================================
    CURRENCY SCOPE — V1
    ================================

    Version 1 of the payment system operates only with IRR.

    This repository deliberately does NOT implement:

        - currency conversion
        - exchange rates
        - money classes
        - multi-currency normalization
        - FX rounding
        - currency arithmetic

    Payment.amount remains a Decimal snapshot and Payment.currency
    remains the explicit currency field.

    Multi-currency support can be introduced later at the domain
    boundary if the business actually requires it.

    ================================
    DATABASE AS FINAL AUTHORITY
    ================================

    Database constraints remain authoritative for structural
    integrity.

    Application-level existence checks are therefore never considered
    sufficient protection against races.

    Example:

        pending payment uniqueness for an Order

    must ultimately be protected by the PostgreSQL unique constraint
    defined on PaymentModel.

    The repository may expose convenient queries, but those queries
    do not replace database constraints.
    """

    model: ClassVar[type[PaymentModel]] = PaymentModel

    # ================================
    # BASE QUERYSET
    # ================================

    @classmethod
    def queryset(cls) -> QuerySet[PaymentModel]:
        """
        Return the base lazy Payment QuerySet.

        No locking.
        No transaction required.
        No business filtering.
        """
        return cls.model.objects.all()

    # ================================
    # REQUIRED READ
    # ================================

    @classmethod
    def get(
        cls,
        payment_id: int,
    ) -> PaymentModel:
        """
        Retrieve a Payment by primary key.

        Raises:
            PaymentModel.DoesNotExist
        """
        return cls.queryset().get(
            pk=payment_id,
        )

    @classmethod
    def find(
        cls,
        payment_id: int,
    ) -> PaymentModel | None:
        """
        Retrieve a Payment if it exists.

        Returns:
            PaymentModel | None

        Does not raise DoesNotExist.
        """
        return (
            cls.queryset()
            .filter(
                pk=payment_id,
            )
            .first()
        )

    # ================================
    # ORDER QUERIES
    # ================================

    @classmethod
    def for_order(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return all Payments belonging to an Order.

        The QuerySet remains lazy.
        """
        return (
            cls.queryset()
            .filter(
                order_id=order_id,
            )
        )

    @classmethod
    def pending_for_order(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return pending Payments belonging to an Order.

        This is a persistence query only.

        It does NOT determine whether creation or retry is allowed.
        """
        return (
            cls.for_order(order_id)
            .filter(
                status=PaymentStatusType.PENDING,
            )
        )

    @classmethod
    def successful_for_order(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return successful Payments belonging to an Order.
        """
        return (
            cls.for_order(order_id)
            .filter(
                status=PaymentStatusType.SUCCESS,
            )
        )

    @classmethod
    def failed_for_order(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return failed Payments belonging to an Order.
        """
        return (
            cls.for_order(order_id)
            .filter(
                status=PaymentStatusType.FAILED,
            )
        )

    @classmethod
    def latest_for_order(
        cls,
        order_id: int,
    ) -> PaymentModel | None:
        """
        Return the latest Payment for an Order.

        Ordering is deterministic:

            -created_date
            -id
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
    def latest_successful_for_order(
        cls,
        order_id: int,
    ) -> PaymentModel | None:
        """
        Return the latest successful Payment for an Order.
        """
        return (
            cls.successful_for_order(order_id)
            .order_by(
                "-updated_date",
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
        Return the latest failed Payment for an Order.
        """
        return (
            cls.failed_for_order(order_id)
            .order_by(
                "-updated_date",
                "-id",
            )
            .first()
        )

    # ================================
    # STATE QUERIES
    # ================================

    @classmethod
    def pending(cls) -> QuerySet[PaymentModel]:
        """
        Return all pending Payments.
        """
        return cls.queryset().filter(
            status=PaymentStatusType.PENDING,
        )

    @classmethod
    def successful(cls) -> QuerySet[PaymentModel]:
        """
        Return all successful Payments.
        """
        return cls.queryset().filter(
            status=PaymentStatusType.SUCCESS,
        )

    @classmethod
    def failed(cls) -> QuerySet[PaymentModel]:
        """
        Return all failed Payments.
        """
        return cls.queryset().filter(
            status=PaymentStatusType.FAILED,
        )

    # ================================
    # ROW LOCKING
    # ================================

    @classmethod
    def get_for_update(
        cls,
        payment_id: int,
    ) -> PaymentModel:
        """
        Retrieve and lock exactly one Payment row.

        SQL semantics:
            SELECT ...
            FROM payment
            WHERE id = ?
            FOR UPDATE

        Transaction ownership belongs to the caller.

        Intended for:
            - state transitions
            - consumption
            - refund workflows
            - reconciliation
            - duplicate callback processing

        The method does NOT lock:
            - Order
            - PaymentAttempt
            - Refund

        If those rows are needed, the application workflow must acquire
        them explicitly according to the canonical lock order.
        """
        return (
            cls.queryset()
            .select_for_update()
            .get(
                pk=payment_id,
            )
        )

    @classmethod
    def get_for_update_nowait(
        cls,
        payment_id: int,
    ) -> PaymentModel:
        """
        Retrieve and lock a Payment using NOWAIT semantics.

        If another transaction already holds the lock, PostgreSQL
        raises the appropriate database lock exception immediately.

        This repository does not translate that database-level locking
        behavior into business policy.
        """
        return (
            cls.queryset()
            .select_for_update(
                nowait=True,
            )
            .get(
                pk=payment_id,
            )
        )

    # ================================
    # ORDER-SCOPED LOCKING
    # ================================

    @classmethod
    def pending_for_order_for_update(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return pending Payments for an Order with row locks.

        Important:

        This locks existing pending Payment rows only.

        It does NOT make a check-then-create operation race-safe by
        itself.

        Creation races must ultimately be protected by the database
        uniqueness constraint.
        """
        return (
            cls.pending_for_order(order_id)
            .select_for_update()
            .order_by(
                "created_date",
                "id",
            )
        )

    @classmethod
    def for_order_for_update(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return all Payments for an Order with row-level locks.

        This method is useful when an application workflow needs a
        deterministic lock over the Payment records belonging to one
        Order.

        It does not lock the Order row itself.
        """
        return (
            cls.for_order(order_id)
            .select_for_update()
            .order_by(
                "created_date",
                "id",
            )
        )

    # ================================
    # WORKER / RECONCILIATION LOCKING
    # ================================

    @classmethod
    def pending_for_update_skip_locked(
        cls,
    ) -> QuerySet[PaymentModel]:
        """
        Return pending Payments using SELECT ... FOR UPDATE SKIP LOCKED.

        Intended for worker/reconciliation workflows.

        Already locked rows are skipped instead of blocking the worker.

        The caller owns:

            transaction.atomic()

        and the worker's processing policy.
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

    # ================================
    # EXISTENCE QUERIES
    # ================================

    @classmethod
    def exists_for_order(
        cls,
        order_id: int,
    ) -> bool:
        """
        Return whether any Payment exists for an Order.

        This is a read convenience only.

        It must NOT be used as a substitute for database constraints
        when preventing duplicate active Payments.
        """
        return (
            cls.queryset()
            .filter(
                order_id=order_id,
            )
            .exists()
        )

    @classmethod
    def exists_pending_for_order(
        cls,
        order_id: int,
    ) -> bool:
        """
        Return whether a pending Payment exists for an Order.

        This is a read optimization/convenience.

        It is NOT a concurrency guarantee.

        The PostgreSQL unique constraint remains authoritative.
        """
        return (
            cls.pending_for_order(order_id)
            .exists()
        )

    # ================================
    # CREATION
    # ================================

    @classmethod
    def create(
        cls,
        **kwargs,
    ) -> PaymentModel:
        """
        Create and persist a new Payment.

        The caller owns:

            - transaction.atomic()
            - business validation
            - policy decisions
            - idempotency decisions

        Database constraints remain authoritative.

        Important:

        A race during creation may result in IntegrityError.

        The repository deliberately does not hide that exception.

        The application service should translate/reconcile the error
        according to its idempotency and creation workflow.
        """
        return cls.model.objects.create(
            **kwargs,
        )

    # ================================
    # OPTIMISTIC CONCURRENCY
    # ================================

    @classmethod
    def save(
        cls,
        payment: PaymentModel,
        *,
        update_fields: list[str] | tuple[str, ...] | None = None,
    ) -> PaymentModel:
        """
        Persist a domain-mutated Payment using compare-and-swap.

        Expected behavior:

            version = N

            UPDATE payment
            SET
                mutable fields = ...,
                version = version + 1
            WHERE
                id = payment.id
                AND version = N

        Exactly one affected row means success.

        Zero affected rows means concurrent modification and results
        in PaymentConcurrencyError.

        --------------------------------------------
        IMPORTANT
        --------------------------------------------

        This method does NOT create transaction.atomic().

        The caller owns the transaction boundary.

        --------------------------------------------
        FINANCIAL IMMUTABILITY
        --------------------------------------------

        ``amount`` and ``currency`` are intentionally rejected from
        ordinary update_fields.

        A Payment financial snapshot must not be silently rewritten.

        --------------------------------------------
        VERSION
        --------------------------------------------

        ``version`` is controlled exclusively by this repository.

        Callers must never manually include ``version`` in
        update_fields.
        """

        if payment.pk is None:
            raise ValueError(
                "Cannot persist an unsaved Payment through optimistic save."
            )

        expected_version = payment.version

        if expected_version < 1:
            raise ValueError(
                "Payment version must be greater than zero."
            )

        # --------------------------------------------
        # Mutable Payment fields
        # --------------------------------------------

        immutable_fields = {
            "amount",
            "currency",
            "order",
        }

        if update_fields is None:
            fields = [
                "status",
                "is_consumed",
                "is_refunded",
            ]
        else:
            fields = list(update_fields)

        # --------------------------------------------
        # Version is repository-controlled.
        # --------------------------------------------

        if "version" in fields:
            fields.remove("version")

        # --------------------------------------------
        # Financial snapshot must remain immutable.
        # --------------------------------------------

        forbidden = immutable_fields.intersection(fields)

        if forbidden:
            forbidden_fields = ", ".join(
                sorted(forbidden)
            )

            raise ValueError(
                "Payment financial/aggregate identity fields cannot "
                "be modified through PaymentRepository.save(): "
                f"{forbidden_fields}"
            )

        # --------------------------------------------
        # updated_date
        #
        # PaymentModel uses auto_now=True, but QuerySet.update() bypasses
        # model save() and therefore does not automatically update it.
        #
        # We explicitly assign timezone.now().
        # --------------------------------------------

        from django.utils import timezone

        update_kwargs = {
            field: getattr(payment, field)
            for field in fields
        }

        update_kwargs["updated_date"] = timezone.now()

        # --------------------------------------------
        # Atomic version increment.
        # --------------------------------------------

        update_kwargs["version"] = F(
            "version"
        ) + 1

        # --------------------------------------------
        # Compare-and-swap.
        # --------------------------------------------

        rows_affected = (
            cls.model.objects
            .filter(
                pk=payment.pk,
                version=expected_version,
            )
            .update(
                **update_kwargs,
            )
        )

        # --------------------------------------------
        # Concurrent modification.
        # --------------------------------------------

        if rows_affected != 1:
            raise PaymentConcurrencyError(
                (
                    "Payment was modified concurrently. "
                    f"payment_id={payment.pk}, "
                    f"expected_version={expected_version}"
                )
            )

        # --------------------------------------------
        # Synchronize in-memory aggregate.
        # --------------------------------------------

        payment.version = (
            expected_version + 1
        )

        payment.updated_date = update_kwargs[
            "updated_date"
        ]

        return payment

    # ================================
    # STATE-SPECIFIC PERSISTENCE
    # ================================

    @classmethod
    def save_status(
        cls,
        payment: PaymentModel,
    ) -> PaymentModel:
        """
        Persist a Payment state mutation.

        Intended for domain commands such as:

            payment.succeed()
            payment.fail()

        Optimistic locking is always applied.
        """
        return cls.save(
            payment,
            update_fields=(
                "status",
            ),
        )

    @classmethod
    def save_consumption(
        cls,
        payment: PaymentModel,
    ) -> PaymentModel:
        """
        Persist Payment consumption state.

        The domain model must already have validated that the operation
        is legal.
        """
        return cls.save(
            payment,
            update_fields=(
                "is_consumed",
            ),
        )

    @classmethod
    def save_refund_state(
        cls,
        payment: PaymentModel,
    ) -> PaymentModel:
        """
        Persist the aggregate-level fully-refunded flag.

        The Refund workflow is responsible for proving that the
        cumulative successful refund amount equals the Payment amount.

        This method merely persists the already-decided domain state.
        """
        return cls.save(
            payment,
            update_fields=(
                "is_refunded",
            ),
        )

    # ================================
    # CONDITIONAL PERSISTENCE HELPERS
    # ================================

    @classmethod
    def mark_consumed_if_current(
        cls,
        *,
        payment_id: int,
        expected_version: int,
    ) -> bool:
        """
        Atomically mark a Payment as consumed if its version matches.

        This is a low-level persistence primitive.

        Business eligibility must be checked by the application/domain
        layer before calling it.

        Returns:

            True
                Exactly one row was modified.

            False
                The expected version no longer matches.

        No transaction boundary is created here.
        """

        if expected_version < 1:
            raise ValueError(
                "Payment version must be greater than zero."
            )

        from django.utils import timezone

        rows_affected = (
            cls.model.objects
            .filter(
                pk=payment_id,
                version=expected_version,
            )
            .update(
                is_consumed=True,
                version=F("version") + 1,
                updated_date=timezone.now(),
            )
        )

        return rows_affected == 1

    # ================================
    # REFUND-RELATED READS
    # ================================

    @classmethod
    def refundable_candidates(
        cls,
    ) -> QuerySet[PaymentModel]:
        """
        Return successful, consumed, not-fully-refunded Payments.

        This is intentionally only a persistence query.

        It does NOT calculate the remaining refundable balance.

        Aggregate refund balance MUST be calculated while the Payment
        row is locked.
        """
        return (
            cls.successful()
            .filter(
                is_consumed=True,
                is_refunded=False,
            )
        )

    @classmethod
    def refundable_candidates_for_update(
        cls,
    ) -> QuerySet[PaymentModel]:
        """
        Return refundable Payment candidates with row locks.

        Intended for refund application workflows.

        The caller must evaluate this QuerySet inside transaction.atomic().
        """
        return (
            cls.refundable_candidates()
            .select_for_update()
            .order_by(
                "created_date",
                "id",
            )
        )

    # ================================
    # INTEGRITY HELPERS
    # ================================

    @classmethod
    def create_safely(
        cls,
        **kwargs,
    ) -> PaymentModel:
        """
        Create a Payment while preserving database integrity semantics.

        This method intentionally does not convert IntegrityError into a
        business exception because the exact reason may matter to the
        application service.

        The caller may inspect the integrity violation and perform the
        appropriate idempotency/retry reconciliation.

        This method exists primarily as an explicit semantic alias for
        creation in concurrency-sensitive application workflows.
        """
        try:
            return cls.create(
                **kwargs,
            )
        except IntegrityError:
            raise

    # ================================
    # REPRESENTATION
    # ================================

    def __repr__(self) -> str:
        return (
            f"<PaymentRepository "
            f"model={self.model.__name__}>"
        )