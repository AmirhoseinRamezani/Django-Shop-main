# payment/repositories/payment_attempt_repository.py
from __future__ import annotations
from django.db.models import Max
from payment.models import PaymentAttempt
from payment.repositories.base import BaseRepository

class PaymentAttemptRepository(BaseRepository):
    """
    Repository for PaymentAttempt.

    Responsibilities

        - CRUD
        - Queries
        - Locks

    Never place business rules here.
    """

    # -----------------------------
    # Read
    # -----------------------------
    @staticmethod
    def get(pk: int) -> PaymentAttempt:

        return PaymentAttempt.objects.get(
            pk=pk,
        )

    @staticmethod
    def for_payment(payment):

        return (
            PaymentAttempt.objects
            .for_payment(payment)
        )

    @staticmethod
    def latest(payment):

        return (
            PaymentAttempt.objects
            .for_payment(payment)
            .order_by("-attempt_number")
            .first()
        )

    @staticmethod
    def successful(payment):

        return (
            PaymentAttempt.objects
            .successful()
            .for_payment(payment)
        )

    @staticmethod
    def failed(payment):

        return (
            PaymentAttempt.objects
            .failed()
            .for_payment(payment)
        )

    @staticmethod
    def pending(payment):

        return (
            PaymentAttempt.objects
            .pending()
            .for_payment(payment)
        )

    @staticmethod
    def timeout(payment):

        return (
            PaymentAttempt.objects
            .timeout()
            .for_payment(payment)
        )

    @staticmethod
    def cancelled(payment):

        return (
            PaymentAttempt.objects
            .cancelled()
            .for_payment(payment)
        )

    # -----------------------------
    # Locks
    # -----------------------------
    @staticmethod
    def lock(pk: int):

        return (
            PaymentAttempt.objects
            .for_update()
            .get(pk=pk)
        )

    @staticmethod
    def latest_for_update(payment):

        return (
            PaymentAttempt.objects
            .for_payment(payment)
            .order_by("-attempt_number")
            .for_update()
            .first()
        )

    # -----------------------------
    # Persistence
    # -----------------------------
    @staticmethod
    def create(**kwargs):

        return PaymentAttempt.objects.create(
            **kwargs,
        )

    @staticmethod
    def save(attempt: PaymentAttempt):

        attempt.save()

        return attempt

    # -----------------------------
    # Exists
    # -----------------------------
    @staticmethod
    def exists_pending(payment):

        return (
            PaymentAttempt.objects
            .pending()
            .for_payment(payment)
            .exists()
        )

    @staticmethod
    def exists_success(payment):

        return (
            PaymentAttempt.objects
            .successful()
            .for_payment(payment)
            .exists()
        )

    # -----------------------------
    # Statistics
    # -----------------------------
    @staticmethod
    def count(payment):

        return (
            PaymentAttempt.objects
            .for_payment(payment)
            .count()
        )

    @staticmethod
    def next_attempt_number(payment):
        """
        Returns the next attempt attempt_number.

        Safe even if previous attempts
        were manually removed.
        """
        latest = (
            PaymentAttempt.objects
            .filter(payment=payment)
            .aggregate(
                value=Max("attempt_number")
            )["value"]
        )
        return (latest or 0) + 1
        # if latest is None:
        #     return 1

        # return latest.attempt_number + 1