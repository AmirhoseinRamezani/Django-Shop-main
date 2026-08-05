# payment/repositories/refund_repository.py
from __future__ import annotations
from typing import Optional
from django.db.models import QuerySet

from payment.models import Refund
from payment.enums import RefundStatus
from payment.repositories.base import BaseRepository
       

class RefundRepository(BaseRepository):
    """
    Repository responsible for Refund persistence.

    Responsibilities

        • Fetch
        • Query
        • Lock
        • Save

    Never contains business rules.
    """

    model = Refund

    # -----------------------------
    # Base
    # -----------------------------
    @classmethod
    def queryset(cls) -> QuerySet:

        return cls.model.objects.all()

    # -----------------------------
    # Read
    # -----------------------------
    @classmethod
    def get(
        cls,
        refund_id: int,
    ) -> Refund:

        return cls.queryset().get(
            pk=refund_id,
        )

    @classmethod
    def for_payment(
        cls,
        payment,
    ) -> QuerySet:

        return (
            cls.queryset()
            .filter(
                payment=payment,
            )
        )

    @classmethod
    def for_attempt(
        cls,
        attempt,
    ) -> QuerySet:

        return (
            cls.queryset()
            .filter(
                attempt=attempt,
            )
        )

    @classmethod
    def successful(
        cls,
        payment,
    ) -> QuerySet:

        return (
            cls.for_payment(payment)
            .filter(
                status=RefundStatus.SUCCESS,
            )
        )

    @classmethod
    def latest(
        cls,
        payment,
    ) -> Optional[Refund]:

        return (
            cls.for_payment(payment)
            .order_by(
                "-created_date",
            )
            .first()
        )

    @classmethod
    def by_reference(
        cls,
        refund_ref_id: str,
    ) -> Optional[Refund]:

        return (
            cls.queryset()
            .filter(
                refund_ref_id=refund_ref_id,
            )
            .first()
        )

    # -----------------------------
    # Locking
    # -----------------------------
    @classmethod
    def lock(
        cls,
        refund_id: int,
    ) -> Refund:

        return (
            cls.queryset()
            .select_for_update()
            .get(
                pk=refund_id,
            )
        )

    @classmethod
    def lock_payment_refunds(
        cls,
        payment,
    ) -> QuerySet:

        return (
            cls.for_payment(payment)
            .select_for_update()
        )

    # -----------------------------
    # Persistence
    # -----------------------------
    @classmethod
    def create(
        cls,
        **kwargs,
    ) -> Refund:

        return cls.model.objects.create(
            **kwargs,
        )

    @classmethod
    def save(
        cls,
        refund: Refund,
        *,
        update_fields=None,
    ) -> Refund:

        refund.save(
            update_fields=update_fields,
        )

        return refund

    # -----------------------------
    # Exists
    # -----------------------------
    @classmethod
    def exists_reference(
        cls,
        refund_ref_id: str,
    ) -> bool:

        return (
            cls.queryset()
            .filter(
                refund_ref_id=refund_ref_id,
            )
            .exists()
        )

    # -----------------------------
    # Statistics
    # -----------------------------
    @classmethod
    def total_refunded_amount(
        cls,
        payment,
    ):

        from django.db.models import Sum

        return (
            cls.successful(payment)
            .aggregate(
                total=Sum("amount"),
            )["total"]
            or 0
        )
