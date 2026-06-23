# order/management/commands/check_order_sla.py

from django.core.management.base import BaseCommand

from order.services.monitoring import (
    stuck_processing_orders,
    delayed_shipments,
)


class Command(BaseCommand):

    help = "Check order SLA violations"

    def handle(self, *args, **kwargs):

        processing = [
            order.id
            for order in stuck_processing_orders()
            if order.is_stuck_in_processing()
        ]

        shipping = [
            order.id
            for order in delayed_shipments()
            if order.is_shipment_delayed()
        ]

        self.stdout.write(
            self.style.WARNING(
                f"Processing violations: {processing}"
            )
        )

        self.stdout.write(
            self.style.WARNING(
                f"Shipping violations: {shipping}"
            )
        )