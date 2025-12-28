# expire_pending_orders.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.db import transaction

from order.models import OrderModel, OrderStatusType


class Command(BaseCommand):
    help = "Expire unpaid pending orders and restore stock"

    @transaction.atomic
    def handle(self, *args, **options):
        threshold = timezone.now() - timedelta(minutes=15)

        orders = (
            OrderModel.objects
            .select_for_update()
            .filter(
                status=OrderStatusType.pending,
                created_date__lt=threshold,
            )
        )

        count = 0

        for order in orders:
            for item in order.items.select_related("product"):
                product = item.product
                product.stock += item.quantity
                product.save(update_fields=["stock"])

            order.status = OrderStatusType.failed
            order.save(update_fields=["status"])

            count += 1

        self.stdout.write(
            self.style.SUCCESS(f"{count} سفارش منقضی شد")
        )
