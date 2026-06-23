# management/commands/expire_pending_orders.py
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from order.services.state_machine import OrderStateMachine

from order.models import OrderModel, OrderStatusType
from order.policies import OrderPolicy
from shop.models import ProductModel
from order.events.order_event import OrderEventType
from order.services.events import record_order_event

class Command(BaseCommand):
    help = "Expire unpaid pending orders and restore stock"

    def handle(self, *args, **options):
        now = timezone.now()

        qs = (
            OrderModel.objects
            .select_for_update()
            .filter(
                status=OrderStatusType.pending,
                expire_at__lte=now,
            )
        )

        expired_count = 0

        with transaction.atomic():
            orders = list(qs)

            if not orders:
                self.stdout.write("No pending orders to expire")
                return

            for order in orders:
                # 🔒 قانون مرکزی
                if not OrderPolicy.can_expire(order):
                    continue

                # 1️⃣ rollback inventory
                # for item in order.order_items.select_related("product"):
                #     ProductModel.objects.filter(
                #         id=item.product_id
                #     ).update(
                #         stock=F("stock") + item.quantity
                #     )

                # 2️⃣ expire order
                
                OrderStateMachine.transition(
                    order=order,
                    to_status=OrderStatusType.cancelled,
                    payload={"reason": "timeout"}
                )

                expired_count += 1

                self.stdout.write(
                    f"Order #{order.id} expired | stock restored"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"{expired_count} order(s) expired successfully"
            )
        )
        
