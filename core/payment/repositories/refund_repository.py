# payment/repositories/refund_repository.py

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from django.db import IntegrityError
from django.db.models import QuerySet, Sum

from payment.enums import RefundStatus
from payment.models.refund import Refund
from payment.repositories.base import BaseRepository


class RefundRepository(BaseRepository):
    """
    Persistence boundary for the Refund aggregate.

    This repository is intentionally persistence-focused.

    Responsibilities
    ----------------
    The repository owns:

        - Refund QuerySets
        - Refund retrieval
        - Refund filtering
        - Refund existence checks
        - Refund row locking
        - Refund creation
        - Refund persistence
        - Refund aggregate read primitives
        - Successful-refund aggregation
        - Database integrity propagation

    The repository does NOT own:

        - transaction.atomic()
        - Payment locking
        - refund business policy
        - refundable-balance calculation
        - cumulative refund authorization
        - gateway communication
        - gateway verification
        - refund orchestration
        - Payment mutation
        - event publishing
        - retry policy
        - idempotency business reconciliation

    ------------------------------------------------
    CONCURRENCY CONTRACT
    ------------------------------------------------

    The Payment row is the canonical synchronization point for refund
    authorization.

    A service responsible for authorizing a new refund should generally:

        1. Enter transaction.atomic().
        2. Lock the Payment row with SELECT ... FOR UPDATE.
        3. Resolve refund idempotency.
        4. Calculate successful refunds for the Payment.
        5. Validate the requested refund against the Payment snapshot.
        6. Create/process the Refund.
        7. Update Payment state when required.
        8. Commit.

    Refund row locks are useful for workflows operating on an existing
    Refund, but they do not replace locking the Payment row when making
    cumulative financial decisions.

    ------------------------------------------------
    DATABASE AUTHORITY
    ------------------------------------------------

    The Refund model/database constraints remain authoritative for:

        - positive refund amount
        - supported currency
        - unique idempotency key
        - lifecycle consistency
        - successful refund gateway identity
        - failed refund failure reason
        - gateway identity uniqueness scoped to Payment

    IntegrityError is intentionally not translated here because the
    application service is the correct layer to determine the business
    meaning of a database conflict.
    """

    model: ClassVar[type[Refund]] = Refund

    # ================================
    # BASE QUERYSET
    # ================================

    @classmethod
    def queryset(cls) -> QuerySet[Refund]:
        """
        Return the base lazy Refund QuerySet.

        This method performs no evaluation and introduces no locking.

        Returns:
            QuerySet[Refund]
        """
        return cls.model.objects.all()

    # ================================
    # BASIC RETRIEVAL
    # ================================

    @classmethod
    def get(
        cls,
        refund_id: int,
    ) -> Refund:
        """
        Retrieve a Refund by primary key.

        Raises:
            Refund.DoesNotExist
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
        Retrieve a Refund by primary key if it exists.

        Returns:
            Refund | None
        """
        return (
            cls.queryset()
            .filter(
                pk=refund_id,
            )
            .first()
        )

    # ================================
    # IDEMPOTENCY
    # ================================

    @classmethod
    def get_by_idempotency_key(
        cls,
        idempotency_key: str,
    ) -> Refund:
        """
        Retrieve a Refund by its idempotency key.

        The uniqueness guarantee is enforced by the database.

        Business reconciliation of an existing Refund belongs to the
        application/service layer.
        """
        return (
            cls.queryset()
            .get(
                idempotency_key=idempotency_key,
            )
        )

    @classmethod
    def find_by_idempotency_key(
        cls,
        idempotency_key: str,
    ) -> Refund | None:
        """
        Retrieve a Refund by idempotency key if it exists.

        This is a non-locking read.
        """
        return (
            cls.queryset()
            .filter(
                idempotency_key=idempotency_key,
            )
            .first()
        )

    @classmethod
    def get_by_idempotency_key_for_update(
        cls,
        idempotency_key: str,
    ) -> Refund:
        """
        Retrieve and lock a Refund by idempotency key.

        The caller owns the transaction boundary.

        Intended for:
            - idempotency reconciliation
            - gateway callback processing
            - refund state reconciliation
        """
        return (
            cls.queryset()
            .select_for_update()
            .get(
                idempotency_key=idempotency_key,
            )
        )

    @classmethod
    def find_by_idempotency_key_for_update(
        cls,
        idempotency_key: str,
    ) -> Refund | None:
        """
        Retrieve and lock an existing Refund by idempotency key.

        Returns:
            Refund | None

        The caller owns transaction.atomic().
        """
        return (
            cls.queryset()
            .select_for_update()
            .filter(
                idempotency_key=idempotency_key,
            )
            .first()
        )

    # ================================
    # PAYMENT QUERIES
    # ================================

    @classmethod
    def for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return all Refunds belonging to a Payment.

        The QuerySet remains lazy.
        """
        return (
            cls.queryset()
            .filter(
                payment_id=payment_id,
            )
        )

    @classmethod
    def pending_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return pending Refunds belonging to a Payment.

        This is a persistence query only.

        It does NOT mean that another refund may or may not be created.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                status=RefundStatus.PENDING,
            )
        )

    @classmethod
    def successful_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return successful Refunds belonging to a Payment.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                status=RefundStatus.SUCCESS,
            )
        )

    @classmethod
    def failed_for_payment(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return failed Refunds belonging to a Payment.
        """
        return (
            cls.for_payment(payment_id)
            .filter(
                status=RefundStatus.FAILED,
            )
        )

    # ================================
    # GLOBAL STATE QUERIES
    # ================================

    @classmethod
    def pending(cls) -> QuerySet[Refund]:
        """
        Return all pending Refunds.

        The QuerySet remains lazy.
        """
        return cls.queryset().filter(
            status=RefundStatus.PENDING,
        )

    @classmethod
    def successful(cls) -> QuerySet[Refund]:
        """
        Return all successful Refunds.

        The QuerySet remains lazy.
        """
        return cls.queryset().filter(
            status=RefundStatus.SUCCESS,
        )

    @classmethod
    def failed(cls) -> QuerySet[Refund]:
        """
        Return all failed Refunds.

        The QuerySet remains lazy.
        """
        return cls.queryset().filter(
            status=RefundStatus.FAILED,
        )

    # ================================
    # ORDERING / LATEST
    # ================================

    @classmethod
    def latest_for_payment(
        cls,
        payment_id: int,
    ) -> Refund | None:
        """
        Return the most recently requested Refund for a Payment.

        Ordering is deterministic through requested_at and id.
        """
        return (
            cls.for_payment(payment_id)
            .order_by(
                "-requested_at",
                "-id",
            )
            .first()
        )

    @classmethod
    def latest_successful_for_payment(
        cls,
        payment_id: int,
    ) -> Refund | None:
        """
        Return the most recently completed successful Refund.
        """
        return (
            cls.successful_for_payment(payment_id)
            .order_by(
                "-finished_at",
                "-id",
            )
            .first()
        )

    @classmethod
    def latest_failed_for_payment(
        cls,
        payment_id: int,
    ) -> Refund | None:
        """
        Return the most recently completed failed Refund.
        """
        return (
            cls.failed_for_payment(payment_id)
            .order_by(
                "-finished_at",
                "-id",
            )
            .first()
        )

    # ================================
    # ROW LOCKING
    # ================================

    @classmethod
    def get_for_update(
        cls,
        refund_id: int,
    ) -> Refund:
        """
        Retrieve and lock a Refund by primary key.

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
    def get_for_update_nowait(
        cls,
        refund_id: int,
    ) -> Refund:
        """
        Retrieve and lock a Refund using NOWAIT semantics.

        If the row is already locked, the database lock exception is
        intentionally propagated to the caller.

        The repository does not translate lock failures into business
        exceptions.
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

    @classmethod
    def get_for_update_skip_locked(
        cls,
        refund_id: int,
    ) -> Refund | None:
        """
        Retrieve and lock a Refund using SKIP LOCKED semantics.

        Returns None when the row is currently locked by another
        transaction.

        This is useful for worker/reconciliation workflows.
        """
        return (
            cls.queryset()
            .select_for_update(
                skip_locked=True,
            )
            .filter(
                pk=refund_id,
            )
            .first()
        )

    @classmethod
    def for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return all Refunds belonging to a Payment with row locks.

        IMPORTANT:

        This does not replace locking the Payment row.

        The Payment row remains the canonical synchronization point for
        cumulative refund authorization.
        """
        return (
            cls.for_payment(payment_id)
            .select_for_update()
            .order_by(
                "requested_at",
                "id",
            )
        )

    @classmethod
    def pending_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return pending Refunds for a Payment with row locks.

        The caller owns transaction.atomic().
        """
        return (
            cls.pending_for_payment(payment_id)
            .select_for_update()
            .order_by(
                "requested_at",
                "id",
            )
        )

    @classmethod
    def successful_for_payment_for_update(
        cls,
        payment_id: int,
    ) -> QuerySet[Refund]:
        """
        Return successful Refunds for a Payment with row locks.

        This is useful when a workflow must operate on the actual
        successful Refund rows.

        It is NOT the primary synchronization mechanism for cumulative
        refund authorization.
        """
        return (
            cls.successful_for_payment(payment_id)
            .select_for_update()
            .order_by(
                "requested_at",
                "id",
            )
        )

    @classmethod
    def pending_for_update_skip_locked(
        cls,
    ) -> QuerySet[Refund]:
        """
        Return pending Refunds using SKIP LOCKED semantics.

        Intended primarily for worker/reconciliation processing.

        Refund rows already locked by another transaction are skipped.

        The caller owns transaction.atomic().
        """
        return (
            cls.pending()
            .select_for_update(
                skip_locked=True,
            )
            .order_by(
                "requested_at",
                "id",
            )
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
        Return the cumulative successful refund amount for a Payment.

        Returns:
            Decimal("0") when no successful Refund exists.

        --------------------------------------------
        CONCURRENCY CONTRACT
        --------------------------------------------

        This is deliberately a read primitive.

        It does NOT:

            - lock Payment
            - lock Refund rows
            - authorize a new refund
            - determine remaining refundable balance

        The application service must lock the Payment row before using
        this value for a financial authorization decision.

        Example:

            with transaction.atomic():
                payment = PaymentRepository.get_for_update(
                    payment_id
                )

                refunded_amount = (
                    RefundRepository
                    .successful_amount_for_payment(
                        payment.pk
                    )
                )

                # Business authorization follows.
        """
        result = (
            cls.successful_for_payment(payment_id)
            .aggregate(
                total=Sum("amount"),
            )
        )

        total = result["total"]

        if total is None:
            return Decimal("0")

        return Decimal(str(total))

    # ================================
    # EXISTENCE QUERIES
    # ================================

    @classmethod
    def exists_for_payment(
        cls,
        payment_id: int,
    ) -> bool:
        """
        Return whether at least one Refund exists for a Payment.

        Read convenience only.
        """
        return (
            cls.for_payment(payment_id)
            .exists()
        )

    @classmethod
    def exists_pending_for_payment(
        cls,
        payment_id: int,
    ) -> bool:
        """
        Return whether a pending Refund exists for a Payment.

        This is not a concurrency guarantee and must not be used alone
        to authorize creation of another Refund.
        """
        return (
            cls.pending_for_payment(payment_id)
            .exists()
        )

    @classmethod
    def exists_successful_for_payment(
        cls,
        payment_id: int,
    ) -> bool:
        """
        Return whether at least one successful Refund exists.
        """
        return (
            cls.successful_for_payment(payment_id)
            .exists()
        )

    @classmethod
    def exists_failed_for_payment(
        cls,
        payment_id: int,
    ) -> bool:
        """
        Return whether at least one failed Refund exists.
        """
        return (
            cls.failed_for_payment(payment_id)
            .exists()
        )

    # ================================
    # GATEWAY IDENTITY QUERIES
    # ================================

    @classmethod
    def find_by_gateway_reference(
        cls,
        gateway_reference: str,
    ) -> Refund | None:
        """
        Find a Refund by gateway reference.

        IMPORTANT:

        The database uniqueness constraint is scoped to Payment.

        Therefore this method must not be treated as proof that the
        gateway reference is globally unique.
        """
        return (
            cls.queryset()
            .filter(
                gateway_reference=gateway_reference,
            )
            .first()
        )

    @classmethod
    def find_by_gateway_reference_for_update(
        cls,
        gateway_reference: str,
    ) -> Refund | None:
        """
        Find and lock a Refund by gateway reference.

        The database uniqueness scope remains Payment-level.
        """
        return (
            cls.queryset()
            .select_for_update()
            .filter(
                gateway_reference=gateway_reference,
            )
            .first()
        )

    @classmethod
    def find_by_gateway_transaction_id(
        cls,
        gateway_transaction_id: str,
    ) -> Refund | None:
        """
        Find a Refund by gateway transaction identifier.

        Database uniqueness is scoped to Payment.
        """
        return (
            cls.queryset()
            .filter(
                gateway_transaction_id=gateway_transaction_id,
            )
            .first()
        )

    @classmethod
    def find_by_gateway_transaction_id_for_update(
        cls,
        gateway_transaction_id: str,
    ) -> Refund | None:
        """
        Find and lock a Refund by gateway transaction identifier.

        The database uniqueness scope remains Payment-level.
        """
        return (
            cls.queryset()
            .select_for_update()
            .filter(
                gateway_transaction_id=gateway_transaction_id,
            )
            .first()
        )

    # ================================
    # CREATION
    # ================================

    @classmethod
    def create(
        cls,
        **kwargs,
    ) -> Refund:
        """
        Create and persist a new Refund.

        The caller owns:

            - transaction.atomic()
            - Payment locking
            - idempotency policy
            - cumulative refund validation
            - currency validation
            - gateway workflow
            - application orchestration

        Database constraints remain authoritative.

        IntegrityError is deliberately propagated.
        """
        return cls.model.objects.create(
            **kwargs,
        )

    @classmethod
    def create_safely(
        cls,
        **kwargs,
    ) -> Refund:
        """
        Semantic alias for concurrency-sensitive Refund creation.

        This method intentionally does not translate IntegrityError.

        Possible database conflicts include:

            - idempotency-key race
            - gateway-reference collision
            - gateway-transaction collision
            - another database constraint violation

        The application service is responsible for interpreting the
        conflict and performing any required reconciliation.
        """
        try:
            return cls.create(
                **kwargs,
            )
        except IntegrityError:
            raise

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
        Persist a domain-mutated Refund.
        --------------------------------------------
        IMMUTABLE FINANCIAL / REQUEST IDENTITY
        --------------------------------------------

        The following fields are immutable after Refund creation:
            - payment
            - payment_id
            - amount
            - currency
            - idempotency_key
            - requested_at

        They define the financial and request identity of the Refund.
        --------------------------------------------
        MUTABLE LIFECYCLE / OBSERVABILITY
        --------------------------------------------

        Mutable fields include:
            - status
            - gateway_reference
            - gateway_transaction_id
            - response_code
            - gateway_message
            - failure_reason
            - finished_at
            - latency_ms
            - ip_address
            - user_agent
            - meta

        The Refund domain model remains responsible for state
        transitions and domain invariant validation.
        """

        if refund.pk is None:
            raise ValueError(
                "Cannot persist an unsaved Refund through "
                "RefundRepository.save()."
            )

        immutable_fields = {
            "payment",
            "payment_id",
            "amount",
            "currency",
            "idempotency_key",
            "requested_at",
        }

        if update_fields is None:
            fields = [
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
            ]
        else:
            fields = list(update_fields)

        # Prevent accidental mutation of the financial/request snapshot.
        forbidden = immutable_fields.intersection(fields)

        if forbidden:
            forbidden_fields = ", ".join(
                sorted(forbidden)
            )

            raise ValueError(
                "Refund financial/request identity fields cannot be "
                "modified through RefundRepository.save(): "
                f"{forbidden_fields}"
            )

        # Empty update_fields would otherwise result in a no-op save.
        # Treating it as an explicit programming error makes repository
        # misuse easier to detect.
        if not fields:
            raise ValueError(
                "RefundRepository.save() requires at least one mutable "
                "field when update_fields is provided."
            )

        refund.save(
            update_fields=fields,
        )

        return refund

    # ================================
    # STATE-SPECIFIC PERSISTENCE
    # ================================

    @classmethod
    def save_status(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist a Refund lifecycle transition.
        The domain object must already contain the desired validated
        state.
        """
        return cls.save(
            refund,
            update_fields=(
                "status",
                "finished_at",
                "latency_ms",
                "failure_reason",
                "gateway_reference",
                "gateway_transaction_id",
                "response_code",
                "gateway_message",
            ),
        )

    @classmethod
    def save_gateway_evidence(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist non-terminal gateway evidence.

        Intended for:
            Refund.register_gateway_response(...)
        """
        return cls.save(
            refund,
            update_fields=(
                "response_code",
                "gateway_message",
            ),
        )

    @classmethod
    def save_success(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist a successful Refund transition.

        The Refund domain model must already have performed:
            - state transition validation
            - gateway identity reconciliation
            - successful-refund invariants
        """
        return cls.save(
            refund,
            update_fields=(
                "status",
                "gateway_reference",
                "gateway_transaction_id",
                "response_code",
                "gateway_message",
                "failure_reason",
                "finished_at",
                "latency_ms",
            ),
        )

    @classmethod
    def save_failure(
        cls,
        refund: Refund,
    ) -> Refund:
        """
        Persist a failed Refund transition.

        The Refund domain model must already have validated the failure
        transition and failure reason.
        """
        return cls.save(
            refund,
            update_fields=(
                "status",
                "response_code",
                "gateway_message",
                "failure_reason",
                "finished_at",
                "latency_ms",
            ),
        )

    # ================================
    # REPRESENTATION
    # ================================

    def __repr__(self) -> str:
        return (
            f"<RefundRepository "
            f"model={self.model.__name__}>"
        )