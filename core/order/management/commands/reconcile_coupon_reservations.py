# core/order/management/commands/reconcile_coupon_reservations.py
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from order.models import (
    CouponReservationReconciliation,
    CouponReservationStatus,
    CouponReconciliationStatus,
    OrderStatusType,
)
from order.services.coupon import CouponService


class Command(BaseCommand):
    help = "Retry and reconcile durable coupon reservation operations"

    def handle(self, *args, **options):
        # The committed PAID/CANCELLED Order evidence is the recovery source if
        # the process died before its on_commit callback ran.
        order_ids = set(
            CouponReservationReconciliation.objects.filter(
                Q(status__in=(CouponReconciliationStatus.PENDING, CouponReconciliationStatus.RETRY))
                | Q(
                    reservation__status=CouponReservationStatus.RESERVED,
                    order__status__in=(OrderStatusType.paid, OrderStatusType.cancelled),
                )
                | Q(
                    reservation__status=CouponReservationStatus.RESERVED,
                    order__status=OrderStatusType.pending,
                    order__expire_at__lte=timezone.now(),
                ),
            ).values_list("order_id", flat=True)
        )
        resolved = 0
        retained = 0
        for order_id in sorted(order_ids):
            if CouponService.reconcile_order(order_id):
                resolved += 1
            else:
                retained += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Coupon reconciliation complete: {resolved} resolved, {retained} retained for review/retry."
            )
        )