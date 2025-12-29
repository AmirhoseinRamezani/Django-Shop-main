from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.db.models import F

from order.models import OrderModel, OrderStatusType
from shop.models import ProductModel


class Command(BaseCommand):
    help = "Expire unpaid pending orders and restore stock"

    def handle(self, *args, **options):
        threshold = timezone.now() - timedelta(minutes=15)

        with transaction.atomic():
            orders = list(
                OrderModel.objects
                .select_for_update()
                .filter(
                    status=OrderStatusType.pending,
                    created_date__lt=threshold,
                )
            )

            if not orders:
                self.stdout.write("No pending orders to expire")
                return

            for order in orders:
                # 1️⃣ rollback inventory
                for item in order.order_items.select_related("product"):
                    ProductModel.objects.filter(
                        id=item.product_id
                    ).update(
                        stock=F("stock") + item.quantity
                    )

                # 2️⃣ mark order cancelled
                order.status = OrderStatusType.cancelled
                order.save(update_fields=["status"])

                self.stdout.write(
                    f"Order #{order.id} expired and stock restored"
                )

        self.stdout.write(
            self.style.SUCCESS("Pending orders cleanup completed")
        )
