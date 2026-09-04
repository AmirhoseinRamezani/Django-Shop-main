# core/payment/repositories/payment_repository.py

from __future__ import annotations

from typing import Any

from django.db.models import F, QuerySet
from django.utils import timezone

from payment.enums import PaymentStatusType
from payment.exceptions import PaymentStaleVersionError
from payment.models import PaymentModel
from payment.repositories.base import BaseRepository


class PaymentRepository(
    BaseRepository[PaymentModel],
):
    """
    Persistence boundary for the Payment aggregate.

    Responsibilities
    ----------------
    This repository owns persistence mechanics for PaymentModel:

        - retrieval
        - filtering
        - ordering
        - row-level locking
        - creation
        - optimistic-concurrency persistence
        - persistence-oriented existence checks
        - state-specific persistence helpers

    Non-responsibilities
    --------------------
    This repository does not own:

        - business policy
        - gateway communication
        - payment verification
        - refund authorization
        - PaymentAttempt workflow
        - Order mutation
        - transaction.atomic()
        - Celery
        - event publication
        - webhook handling
        - reconciliation decisions
        - state-transition decisions

    Domain decisions belong to the domain/application layers.

    Transaction ownership
    ---------------------
    This repository never creates transaction boundaries.

    Application services own transaction.atomic().

    Locking contract
    ----------------
    get_for_update() and other locking methods require an active
    database transaction.

    Payment is the canonical aggregate lock for workflows involving:

        - payment state
        - payment consumption
        - cumulative refunds
        - reconciliation
        - duplicate callback handling

    Canonical lock order when multiple Payment Core records are involved:

        Payment
            ->
        PaymentAttempt
            ->
        Refund

    The repository never implicitly locks child records.

    Optimistic concurrency
    ----------------------
    PaymentModel.version is an optimistic concurrency token.

    Normal persistence uses compare-and-swap semantics:

        UPDATE payment
        SET
            mutable_fields = ...,
            version = version + 1
        WHERE
            id = ?
            AND version = ?

    Exactly one affected row means success.

    Zero affected rows means another transaction changed the aggregate and
    PaymentConcurrencyError is raised.

    Financial immutability
    ----------------------
    Payment.amount and Payment.currency are immutable financial snapshot
    fields.

    They must not be modified through normal PaymentRepository.save().

    Financial corrections must be represented as new domain facts rather
    than rewriting the original Payment snapshot.

    Database authority
    ------------------
    Application-level existence checks are convenience queries only.

    Database constraints remain authoritative for structural integrity and
    concurrency-sensitive uniqueness.
    """

    model = PaymentModel

    # ============================
    # BASE QUERYSET
    # ============================

    @classmethod
    def queryset(
        cls,
    ) -> QuerySet[PaymentModel]:
        """
        Return the base lazy Payment QuerySet.

        No locking.
        No transaction requirement.
        No business filtering.
        """

        return cls.model.objects.all()

    # ============================
    # REQUIRED READ
    # ============================

    @classmethod
    def get(
        cls,
        payment_id: int,
    ) -> PaymentModel:
        """
        Retrieve a Payment by primary key.

        Django's DoesNotExist exception is intentionally preserved.
        """

        return cls.queryset().get(
            pk=payment_id,
        )

    # ============================
    # OPTIONAL READ
    # ============================

    @classmethod
    def find(
        cls,
        payment_id: int,
    ) -> PaymentModel | None:
        """
        Retrieve a Payment if it exists.
        """

        return (
            cls.queryset()
            .filter(
                pk=payment_id,
            )
            .first()
        )

    # ============================
    # ORDER QUERIES
    # ============================

    @classmethod
    def for_order(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return all Payments belonging to an Order.
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
        Return pending Payments belonging to an Order.

        This is a persistence query only.

        It does not determine whether creation or retry is allowed.
        """

        return cls.for_order(
            order_id,
        ).filter(
            status=PaymentStatusType.PENDING,
        )

    @classmethod
    def successful_for_order(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return successful Payments belonging to an Order.
        """

        return cls.for_order(
            order_id,
        ).filter(
            status=PaymentStatusType.SUCCESS,
        )

    @classmethod
    def failed_for_order(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return failed Payments belonging to an Order.
        """

        return cls.for_order(
            order_id,
        ).filter(
            status=PaymentStatusType.FAILED,
        )

    @classmethod
    def latest_for_order(
        cls,
        order_id: int,
    ) -> PaymentModel | None:
        """
        Return the latest Payment for an Order.

        Ordering is deterministic:

            - created_date
            - id
        """

        return (
            cls.for_order(
                order_id,
            )
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
            cls.successful_for_order(
                order_id,
            )
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
            cls.failed_for_order(
                order_id,
            )
            .order_by(
                "-updated_date",
                "-id",
            )
            .first()
        )

    # ============================
    # STATE QUERIES
    # ============================

    @classmethod
    def pending(
        cls,
    ) -> QuerySet[PaymentModel]:
        """
        Return all pending Payments.
        """

        return cls.queryset().filter(
            status=PaymentStatusType.PENDING,
        )

    @classmethod
    def successful(
        cls,
    ) -> QuerySet[PaymentModel]:
        """
        Return all successful Payments.
        """

        return cls.queryset().filter(
            status=PaymentStatusType.SUCCESS,
        )

    @classmethod
    def failed(
        cls,
    ) -> QuerySet[PaymentModel]:
        """
        Return all failed Payments.
        """

        return cls.queryset().filter(
            status=PaymentStatusType.FAILED,
        )

    # ============================
    # ROW LOCKING
    # ============================

    @classmethod
    def get_for_update(
        cls,
        payment_id: int,
    ) -> PaymentModel:
        """
        Retrieve and lock exactly one Payment row.

        The caller MUST execute this inside transaction.atomic().

        This is the canonical Payment aggregate lock.
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

        Database-level lock exceptions are intentionally preserved.
        Business policy belongs to the application layer.
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

    # ============================
    # ORDER-SCOPED LOCKING
    # ============================

    @classmethod
    def pending_for_order_for_update(
        cls,
        order_id: int,
    ) -> QuerySet[PaymentModel]:
        """
        Return pending Payments for an Order with row locks.

        This locks existing rows only.

        It does NOT make check-then-create logic race-safe.

        Database uniqueness remains authoritative.
        """

        return (
            cls.pending_for_order(
                order_id,
            )
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

        The Order row itself is not locked.
        """

        return (
            cls.for_order(
                order_id,
            )
            .select_for_update()
            .order_by(
                "created_date",
                "id",
            )
        )

    # ============================
    # WORKER / RECONCILIATION LOCKING
    # ============================

    @classmethod
    def pending_for_update_skip_locked(
        cls,
    ) -> QuerySet[PaymentModel]:
        """
        Return pending Payments using SKIP LOCKED semantics.

        Intended for reconciliation/worker workflows.

        Already locked rows are skipped instead of blocking.
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

    # ============================
    # EXISTENCE QUERIES
    # ============================

    @classmethod
    def exists_for_order(
        cls,
        order_id: int,
    ) -> bool:
        """
        Return whether any Payment exists for an Order.

        Read convenience only.

        This does not replace database constraints.
        """

        return (
            cls.for_order(
                order_id,
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

        This is not a concurrency guarantee.
        """

        return (
            cls.pending_for_order(
                order_id,
            )
            .exists()
        )

    # ============================
    # CREATION
    # ============================

    @classmethod
    def create(
        cls,
        **kwargs: Any,
    ) -> PaymentModel:
        """
        Create and persist a Payment.

        The caller owns:

            - transaction.atomic()
            - business validation
            - policy decisions
            - idempotency decisions

        IntegrityError is intentionally preserved.
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

        Concurrency contract:

            version = N

            UPDATE payment
            SET
                mutable fields = ...,
                version = version + 1
            WHERE
                id = ?
                AND version = N

        Exactly one affected row means success.
        Zero affected rows means that another transaction changed the
        Payment aggregate.
        The repository never silently overwrites concurrent changes.
        Transaction ownership belongs to the caller.
        Financial identity fields are immutable and cannot be modified
        through this method.
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
        # Explicit mutable-field whitelist
        # --------------------------------------------

        mutable_fields = {
            "status",
            "is_consumed",
            "is_refunded",
        }

        if update_fields is None:
            fields = tuple(
                mutable_fields
            )
        else:
            fields = tuple(
                dict.fromkeys(
                    update_fields
                )
            )

        if not fields:
            raise ValueError(
                "PaymentRepository.save() requires at least one update field."
            )

        # --------------------------------------------
        # Repository-controlled version
        # --------------------------------------------

        if "version" in fields:
            raise ValueError(
                "Payment version is controlled exclusively "
                "by PaymentRepository.save()."
            )

        # --------------------------------------------
        # Reject unsupported fields
        # --------------------------------------------

        unsupported_fields = set(fields) - mutable_fields

        if unsupported_fields:
            field_names = ", ".join(
                sorted(
                    unsupported_fields
                )
            )

            raise ValueError(
                "PaymentRepository.save() received unsupported "
                f"Payment fields: {field_names}"
            )

        # --------------------------------------------
        # Build update payload
        # --------------------------------------------

        update_kwargs = {
            field: getattr(
                payment,
                field,
            )
            for field in fields
        }

        updated_date = timezone.now()

        update_kwargs["updated_date"] = updated_date

        # --------------------------------------------
        # Atomic version increment
        # --------------------------------------------

        update_kwargs["version"] = F(
            "version"
        ) + 1

        # --------------------------------------------
        # Compare-and-swap
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
        # Concurrent modification
        # --------------------------------------------

        if rows_affected != 1:
            raise PaymentStaleVersionError(
                (
                    "Payment was modified concurrently. "
                    f"payment_id={payment.pk}, "
                    f"expected_version={expected_version}"
                )
            )

        # --------------------------------------------
        # Synchronize in-memory aggregate
        # --------------------------------------------

        payment.version = (
            expected_version + 1
        )

        payment.updated_date = updated_date

        return payment

    # ============================
    # STATE-SPECIFIC PERSISTENCE
    # ============================

    @classmethod
    def save_status(
        cls,
        payment: PaymentModel,
    ) -> PaymentModel:
        """
        Persist a Payment status transition.

        The domain model must already have validated the transition.
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

        The Refund workflow is responsible for proving that:

            successful_refund_total == payment.amount

        This method only persists the already-decided domain state.
        """

        return cls.save(
            payment,
            update_fields=(
                "is_refunded",
            ),
        )

    # ============================
    # CONDITIONAL PERSISTENCE
    # ============================

    @classmethod
    def mark_consumed_if_current(
        cls,
        *,
        payment_id: int,
        expected_version: int,
    ) -> bool:
        """
        Atomically mark a Payment as consumed if its version matches.

        Returns:

            True:
                exactly one row was modified.

            False:
                expected version no longer matches.

        No transaction boundary is created here.
        """

        if expected_version < 1:
            raise ValueError(
                "Payment version must be greater than zero."
            )

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

    # ============================
    # REFUND-RELATED READS
    # ============================

    @classmethod
    def refundable_candidates(
        cls,
    ) -> QuerySet[PaymentModel]:
        """
        Return successful, consumed, not-fully-refunded Payments.

        This is only a persistence query.

        Remaining refundable balance must be calculated while the Payment
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

        Caller must evaluate the QuerySet inside transaction.atomic().
        """

        return (
            cls.refundable_candidates()
            .select_for_update()
            .order_by(
                "created_date",
                "id",
            )
        )

    # ============================
    # REPRESENTATION
    # ============================

    def __repr__(self) -> str:
        return (
            f"<PaymentRepository "
            f"model={self.model.__name__}>"
        )