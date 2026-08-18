# core/payment/repositories/gateway_log_repository.py

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from payment.enums import GatewayLogType
from payment.models import GatewayLog
from payment.repositories.base import BaseRepository

class GatewayLogRepository(BaseRepository[GatewayLog]):
    """
    Repository for immutable GatewayLog audit records.

    Architectural responsibility
    ----------------------------
    This repository provides persistence-oriented querying for
    GatewayLog.

    GatewayLog is an append-only audit entity.

    The repository MUST NOT:
        - mutate persisted GatewayLog records
        - execute gateway communication
        - own transactions
        - implement payment business rules
        - implement refund business rules
        - perform state transitions
        - decide idempotency
        - publish events
        - calculate financial amounts

    Transaction boundaries belong to application services.

    GatewayLog ownership
    --------------------
    Every GatewayLog belongs to exactly one operation:
        PaymentAttempt XOR Refund

    Therefore repository queries are intentionally scoped around
    PaymentAttempt and Refund rather than Payment itself.
    """

    model = GatewayLog

    # ================================
    # Base QuerySet
    # ================================

    @classmethod
    def queryset(cls) -> QuerySet[GatewayLog]:
        """
        Return the base immutable GatewayLog queryset.

        The queryset remains lazy and is intentionally not locked.
        """

        return cls.model.objects.all()

    # ================================
    # Creation
    # ================================

    @classmethod
    def create(
        cls,
        **kwargs: Any,
    ) -> GatewayLog:
        """
        Create one immutable GatewayLog record.

        GatewayLog.save() enforces:

            - model validation
            - ownership invariant
            - append-only persistence

        Database constraints remain authoritative.
        """

        return cls.model.objects.create(
            **kwargs,
        )

    # ================================
    # Attempt Queries
    # ================================

    @classmethod
    def for_attempt(
        cls,
        attempt_id: int,
    ) -> QuerySet[GatewayLog]:
        """
        Return all gateway logs belonging to one PaymentAttempt.
        """

        return (
            cls.queryset()
            .filter(
                attempt_id=attempt_id,
            )
            .order_by(
                "created_date",
                "id",
            )
        )

    @classmethod
    def latest_for_attempt(
        cls,
        attempt_id: int,
    ) -> GatewayLog | None:
        """
        Return the latest gateway log for a PaymentAttempt.

        No business decision is made here.
        """

        return (
            cls.queryset()
            .filter(
                attempt_id=attempt_id,
            )
            .order_by(
                "-created_date",
                "-id",
            )
            .first()
        )

    # ================================
    # Refund Queries
    # ================================

    @classmethod
    def for_refund(
        cls,
        refund_id: int,
    ) -> QuerySet[GatewayLog]:
        """
        Return all gateway logs belonging to one Refund.
        """

        return (
            cls.queryset()
            .filter(
                refund_id=refund_id,
            )
            .order_by(
                "created_date",
                "id",
            )
        )

    @classmethod
    def latest_for_refund(
        cls,
        refund_id: int,
    ) -> GatewayLog | None:
        """
        Return the latest gateway log for a Refund.
        """

        return (
            cls.queryset()
            .filter(
                refund_id=refund_id,
            )
            .order_by(
                "-created_date",
                "-id",
            )
            .first()
        )

    # ================================
    # Result Queries
    # ================================

    @classmethod
    def successful(
        cls,
    ) -> QuerySet[GatewayLog]:
        """
        Return gateway communications normalized as successful.

        This describes gateway communication evidence.

        It does NOT mean that the Payment or Refund domain operation
        itself is financially successful.
        """

        return cls.queryset().filter(
            is_success=True,
        )

    @classmethod
    def failed(
        cls,
    ) -> QuerySet[GatewayLog]:
        """
        Return gateway communications normalized as failed.
        """

        return cls.queryset().filter(
            is_success=False,
        )

    @classmethod
    def unresolved(
        cls,
    ) -> QuerySet[GatewayLog]:
        """
        Return gateway communications for which no normalized result
        has been determined yet.

        is_success = NULL
        """

        return cls.queryset().filter(
            is_success__isnull=True,
        )

    # ================================
    # Log Type Queries
    # ================================

    @classmethod
    def requests(
        cls,
    ) -> QuerySet[GatewayLog]:
        """
        Return outbound gateway request logs.
        """

        return cls.queryset().filter(
            log_type=GatewayLogType.REQUEST,
        )

    @classmethod
    def verifies(
        cls,
    ) -> QuerySet[GatewayLog]:
        """
        Return gateway verification logs.
        """

        return cls.queryset().filter(
            log_type=GatewayLogType.VERIFY,
        )

    @classmethod
    def callbacks(
        cls,
    ) -> QuerySet[GatewayLog]:
        """
        Return callback communication logs.
        """

        return cls.queryset().filter(
            log_type=GatewayLogType.CALLBACK,
        )

    @classmethod
    def webhooks(
        cls,
    ) -> QuerySet[GatewayLog]:
        """
        Return webhook communication logs.
        """

        return cls.queryset().filter(
            log_type=GatewayLogType.WEBHOOK,
        )

    # ================================
    # Gateway Queries
    # ================================

    @classmethod
    def for_gateway(
        cls,
        gateway: str,
    ) -> QuerySet[GatewayLog]:
        """
        Return gateway logs for one gateway identifier.
        """

        return cls.queryset().filter(
            gateway=gateway,
        )

    @classmethod
    def for_gateway_type(
        cls,
        gateway: str,
        log_type: str,
    ) -> QuerySet[GatewayLog]:
        """
        Return logs for one gateway and communication type.
        """

        return cls.queryset().filter(
            gateway=gateway,
            log_type=log_type,
        )

    # ================================
    # Response Code Queries
    # ================================

    @classmethod
    def by_response_code(
        cls,
        code: str,
    ) -> QuerySet[GatewayLog]:
        """
        Find logs by normalized gateway response code.
        """

        return cls.queryset().filter(
            response_code=code,
        )

    # ================================
    # HTTP Queries
    # ================================

    @classmethod
    def by_http_status(
        cls,
        status: int,
    ) -> QuerySet[GatewayLog]:
        """
        Find logs by HTTP response status.
        """

        return cls.queryset().filter(
            http_status=status,
        )

    @classmethod
    def transport_failures(
        cls,
    ) -> QuerySet[GatewayLog]:
        """
        Return logs representing transport-level HTTP failures.

        This is technical evidence only.

        It must not be interpreted as a Payment/Refund failure
        without application-level reconciliation.
        """

        return cls.queryset().filter(
            http_status__gte=400,
            http_status__lte=599,
        )

    # ================================
    # Exception Queries
    # ================================

    @classmethod
    def with_exception(
        cls,
    ) -> QuerySet[GatewayLog]:
        """
        Return gateway communications with a captured exception.
        """

        return (
            cls.queryset()
            .exclude(
                exception="",
            )
        )

    # ================================
    # Historical Ordering
    # ================================

    @classmethod
    def chronological(
        cls,
    ) -> QuerySet[GatewayLog]:
        """
        Return all gateway logs in chronological order.

        created_date alone is not sufficient for deterministic
        ordering when multiple records have the same timestamp,
        therefore id is used as the secondary ordering key.
        """

        return (
            cls.queryset()
            .order_by(
                "created_date",
                "id",
            )
        )

    @classmethod
    def latest(
        cls,
    ) -> GatewayLog | None:
        """
        Return the latest GatewayLog globally.

        This is intended for operational/audit tooling and should
        not be used to determine financial state.
        """

        return (
            cls.queryset()
            .order_by(
                "-created_date",
                "-id",
            )
            .first()
        )