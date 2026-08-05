# payment/managers.py
from django.db import models
from django.db.models import Q

from payment.enums import (
    PaymentStatusType,
    PaymentAttemptStatus,
    RefundStatus,
    GatewayLogType,
    GatewayLogDirection,
)

# ===============================
# Payment
# ===============================
class PaymentQuerySet(models.QuerySet):

    # ----------------------------
    # States
    # ----------------------------
    def pending(self):
        return self.filter(
            status=PaymentStatusType.PENDING,
        )

    def successful(self):
        return self.filter(
            status=PaymentStatusType.SUCCESS,
        )

    def failed(self):
        return self.filter(
            status=PaymentStatusType.FAILED,
        )

    def verified(self):
        return self.filter(
            status=PaymentStatusType.SUCCESS,
            verified_date__isnull=False,
        )

    def consumed(self):
        return self.filter(
            is_consumed=True,
        )

    def refunded(self):
        return self.filter(
            is_refunded=True,
        )

    def open(self):
        return self.filter(
            status=PaymentStatusType.PENDING,
            closed_date__isnull=True,
            is_consumed=False,
            is_refunded=False,
        )

    def completed(self):
        return (
            self.successful()
            .consumed()
        )
    
    

    # ----------------------------
    # Filters
    # ----------------------------
    def for_order(self, order):
        return self.filter(
            order=order,
        )

    def by_authority(self, authority):
        return self.filter(
            authority_id=authority,
        )

    def by_reference(self, ref_id):
        return self.filter(
            ref_id=ref_id,
        )

    def by_gateway(self, gateway):
        return self.filter(
            gateway=gateway,
        )

    # ----------------------------
    # Locking
    # ----------------------------
    def for_update(self):
        return self.select_for_update()

    def for_update_skip_locked(self):
        return self.select_for_update(
            skip_locked=True,
        )

    def with_order(self):
        return self.select_related(
            "order",
        )


class PaymentManager(
    models.Manager.from_queryset(
        PaymentQuerySet
    )
):
    def active(self):
        return self.get_queryset().open()
    
    # def open(self):
    #     return self.get_queryset().filter(
    #         status=PaymentStatusType.PENDING,
    #         closed_date__isnull=True,
    #         is_consumed=False,
    #         is_refunded=False,
    #     )

    def closed(self):
        return self.get_queryset().filter(
            closed_date__isnull=False,
        )


# ===============================
# Payment Attempt
# ===============================
class PaymentAttemptQuerySet(models.QuerySet):

    def pending(self):
        return self.filter(
            status=PaymentAttemptStatus.PENDING,
        )

    def successful(self):
        return self.filter(
            status=PaymentAttemptStatus.SUCCESS,
        )

    def failed(self):
        return self.filter(
            status=PaymentAttemptStatus.FAILED,
        )

    def timeout(self):
        return self.filter(
            status=PaymentAttemptStatus.TIMEOUT,
        )

    def cancelled(self):
        return self.filter(
            status=PaymentAttemptStatus.CANCELLED,
        )

    def ordered_latest(self):
        return self.order_by(
            "-attempt_number",
        )

    def for_payment(self, payment):
        return self.filter(
            payment=payment,
        )

    def for_update(self):
        return self.select_for_update()

    def with_payment(self):
        return self.select_related(
            "payment",
        )

    # def latest(self):
    #     return self.order_by("-attempt_number")
    
class PaymentAttemptManager(
    models.Manager.from_queryset(
        PaymentAttemptQuerySet
    )
):
    pass


# ===============================
# Refund
# ===============================
class RefundQuerySet(models.QuerySet):

    def pending(self):
        return self.filter(
            status=RefundStatus.PENDING,
        )

    def successful(self):
        return self.filter(
            status=RefundStatus.SUCCESS,
        )

    def failed(self):
        return self.filter(
            status=RefundStatus.FAILED,
        )

    def for_payment(self, payment):
        return self.filter(
            payment=payment,
        )

    def for_update(self):
        return self.select_for_update()

    def with_payment(self):
        return self.select_related(
            "payment",
        )


class RefundManager(
    models.Manager.from_queryset(
        RefundQuerySet
    )
):
    pass


# ===============================
# Gateway Log
# ===============================
class GatewayLogQuerySet(models.QuerySet):

    def successful(self):
        return self.filter(
            is_success=True,
        )

    def failed(self):
        return self.filter(
            is_success=False,
        )

    def unresolved(self):
        return self.filter(
            is_success__isnull=True,
        )

    def for_attempt(self, attempt):
        return self.filter(
            attempt=attempt,
        )

    def for_refund(self, refund):
        return self.filter(
            refund=refund,
        )

    def for_payment(self, payment):
        return self.filter(
            Q(
                attempt__payment=payment,
            )
            | Q(
                refund__payment=payment,
            )
        )

    def for_gateway(self, gateway):
        return self.filter(
            gateway=gateway,
        )

    def by_type(self, log_type):
        return self.filter(
            log_type=log_type,
        )

    def inbound(self):
        return self.filter(
            direction=GatewayLogDirection.INBOUND,
        )

    def outbound(self):
        return self.filter(
            direction=GatewayLogDirection.OUTBOUND,
        )

    def errors(self):
        return self.filter(
            log_type=GatewayLogType.ERROR,
        )

    def with_attempt(self):
        return self.select_related(
            "attempt",
            "attempt__payment",
        )

    def with_refund(self):
        return self.select_related(
            "refund",
            "refund__payment",
        )

    def with_owner(self):
        return self.select_related(
            "attempt",
            "attempt__payment",
            "refund",
            "refund__payment",
        )

class GatewayLogManager(
    models.Manager.from_queryset(
        GatewayLogQuerySet
    )
):
    pass