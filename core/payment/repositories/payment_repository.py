# payment/repositories/payment_repository.py
from __future__ import annotations
from typing import Optional
from django.db.models import QuerySet
from payment.enums import PaymentStatusType
from payment.models import PaymentModel
from payment.repositories.base import BaseRepository

class PaymentRepository(BaseRepository):
    """
    Repository responsible only for Payment persistence.
    Responsibilities

        • Fetch
        • Query
        • Row Lock
        • Save

    Never contains business rules.
    """

    model = PaymentModel

    # -----------------------------
    # Base
    # -----------------------------
    @classmethod
    def queryset(cls) -> QuerySet:
        return cls.model.objects.all()

    # -----------------------------
    # Getters
    # -----------------------------
    @classmethod
    def get(cls, payment_id: int) -> PaymentModel:
        return cls.queryset().get(pk=payment_id)

    @classmethod
    def by_authority(cls, authority: str) -> PaymentModel:
        return cls.queryset().get(
            authority_id=authority,
        )

    @classmethod
    def by_idempotency_key(cls, key):
        return cls.queryset().get(
            idempotency_key=key,
        )

    @classmethod
    def by_reference(cls, ref_id: str):
        return cls.queryset().filter(
            ref_id=ref_id,
        ).first()

    # -----------------------------
    # Order
    # -----------------------------

    @classmethod
    def for_order(
        cls,
        order,
    ) -> QuerySet:

        return (
            cls.queryset()
            .filter(order=order)
        )

    @classmethod
    def pending(
        cls,
        order,
    ) -> QuerySet:

        return (
            cls.for_order(order)
            .filter(
                status=PaymentStatusType.PENDING,
            )
        )

    @classmethod
    def latest(
        cls,
        order,
    ) -> Optional[PaymentModel]:

        return (
            cls.for_order(order)
            .order_by("-created_date")
            .first()
        )

    @classmethod
    def latest_success(
        cls,
        order,
    ) -> Optional[PaymentModel]:

        return (
            cls.for_order(order)
            .filter(
                status=PaymentStatusType.SUCCESS,
            )
            .order_by("-verified_date")
            .first()
        )

    @classmethod
    def latest_failed(
        cls,
        order,
    ) -> Optional[PaymentModel]:
        return (
            cls.for_order(order)
            .filter(
                status=PaymentStatusType.FAILED,
            )
            .order_by("-updated_date")
            .first()
        )
        
    @classmethod
    def verified(cls):
        return (
            cls.queryset()
            .verified()
        )
        
    @classmethod
    def create(cls, **kwargs):

        return cls.model.objects.create(**kwargs)

    # -----------------------------
    # Locking
    # -----------------------------

    @classmethod
    def lock(
        cls,
        payment_id: int,
    ) -> PaymentModel:

        return (
            cls.queryset()
            .select_for_update()
            .get(pk=payment_id)
        )

    @classmethod
    def by_authority_for_update(
        cls,
        authority: str,
    ) -> PaymentModel:

        return (
            cls.queryset()
            .select_for_update()
            .get(
                authority_id=authority,
            )
        )

    @classmethod
    def lock_pending_for_order(
        cls,
        order,
    ) -> QuerySet:

        return (
            cls.pending(order)
            .select_for_update()
        )

    @classmethod
    def lock_open_skip_locked(
        cls,
    ) -> QuerySet:
        """
        Worker-safe queue.

        Used by reconciliation workers.
        """

        return (
            cls.queryset()
            .filter(
                status=PaymentStatusType.PENDING,
            )
            .select_for_update(
                skip_locked=True,
            )
        )

    # -----------------------------
    # Persistence
    # -----------------------------

    @classmethod
    def save(
        cls,
        payment: PaymentModel,
        *,
        update_fields=None,
    ) -> PaymentModel:

        payment.save(
            update_fields=update_fields,
        )

        return payment

    # -----------------------------
    # Exists
    # -----------------------------

    @classmethod
    def exists_reference(
        cls,
        ref_id: str,
    ) -> bool:

        return (
            cls.queryset()
            .filter(ref_id=ref_id)
            .exists()
        )

    @classmethod
    def exists_authority(
        cls,
        authority: str,
    ) -> bool:

        return (
            cls.queryset()
            .filter(
                authority_id=authority,
            )
            .exists()
        )
        
    
    # # ==========================================================
    # # Aggregate Queries
    # # ==========================================================

    # @property
    # def pending_attempt(self):
    #     """
    #     Current pending gateway execution.
    #     """
    #     from payment.enums import PaymentAttemptStatus

    #     return (
    #         self.attempts
    #         .filter(
    #             status=PaymentAttemptStatus.PENDING,
    #         )
    #         .order_by(
    #             "-attempt_number",
    #         )
    #         .first()
    #     )

    # @property
    # def failed_attempts(self):
    #     from payment.enums import PaymentAttemptStatus

    #     return (
    #         self.attempts
    #         .filter(
    #             status=PaymentAttemptStatus.FAILED,
    #         )
    #     )

    # @property
    # def timeout_attempts(self):
    #     from payment.enums import PaymentAttemptStatus

    #     return (
    #         self.attempts
    #         .filter(
    #             status=PaymentAttemptStatus.TIMEOUT,
    #         )
    #     )

    # @property
    # def cancelled_attempts(self):
    #     from payment.enums import PaymentAttemptStatus

    #     return (
    #         self.attempts
    #         .filter(
    #             status=PaymentAttemptStatus.CANCELLED,
    #         )
    #     )

    # @property
    # def has_attempts(self) -> bool:
    #     return self.attempts.exists()

    # @property
    # def has_successful_attempt(self) -> bool:
    #     return self.successful_attempt is not None

