# payment/repositories/gateway_log_repository.py
from __future__ import annotations
from django.db.models import QuerySet
from payment.models import GatewayLog
from payment.enums import GatewayLogType
from payment.repositories.base import BaseRepository

class GatewayLogRepository(BaseRepository):
    """
    Read-only repository for GatewayLog.

    GatewayLog is immutable.
    """
    model = GatewayLog
    # -----------------------------
    # Base
    # -----------------------------
    @classmethod
    def queryset(cls) -> QuerySet:

        return cls.model.objects.all()

    # -----------------------------
    # Create
    # -----------------------------
    @classmethod
    def create(
        cls,
        **kwargs,
    ) -> GatewayLog:

        return cls.model.objects.create(
            **kwargs,
        )
    # -----------------------------
    # Payment
    # -----------------------------
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
    def successful(
        cls,
        payment,
    ) -> QuerySet:

        return (
            cls.for_payment(payment)
            .filter(
                is_success=True,
            )
        )

    @classmethod
    def failed(
        cls,
        payment,
    ) -> QuerySet:

        return (
            cls.for_payment(payment)
            .filter(
                is_success=False,
            )
        )

    # -----------------------------
    # Attempt
    # -----------------------------
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

    # -----------------------------
    # Refund
    # -----------------------------
    @classmethod
    def for_refund(
        cls,
        refund,
    ) -> QuerySet:

        return (
            cls.queryset()
            .filter(
                refund=refund,
            )
        )

    # -----------------------------
    # Search
    # -----------------------------
    @classmethod
    def by_gateway_reference(
        cls,
        reference: str,
    ) -> QuerySet:

        return (
            cls.queryset()
            .filter(
                gateway_reference=reference,
            )
        )

    @classmethod
    def by_response_code(
        cls,
        code: str,
    ) -> QuerySet:

        return (
            cls.queryset()
            .filter(
                response_code=code,
            )
        )
        
    @classmethod
    def requests(cls):
        return cls.queryset().filter(
            log_type=GatewayLogType.REQUEST,
        )

    @classmethod
    def verifies(cls):
        return cls.queryset().filter(
            log_type=GatewayLogType.VERIFY,
        )
    
    # ________
    @classmethod
    def callbacks(cls):
        return (
            cls.queryset()
            .filter(
                log_type=GatewayLogType.CALLBACK,
            )
        )
        
    @classmethod
    def webhooks(cls):
        return (
            cls.queryset()
            .filter(
                log_type=GatewayLogType.WEBHOOK,
            )
        )