# order/services/sla_monitoring.py
from django.utils import timezone
from order.models import OrderModel, OrderStatusType


class OrderSLAMonitor:

    PROCESSING_LIMIT_HOURS = 24
    SHIPPING_LIMIT_HOURS = 48

    @classmethod
    def find_processing_violations(cls):
        return OrderModel.objects.filter(
            status=OrderStatusType.processing,
        )

    @classmethod
    def find_shipping_violations(cls):
        return OrderModel.objects.filter(
            status=OrderStatusType.paid,
        )

    @classmethod
    def scan(cls):
        processing = []
        shipping = []

        for order in cls.find_processing_violations():
            if order.is_stuck_in_processing(cls.PROCESSING_LIMIT_HOURS):
                processing.append(order)

        for order in cls.find_shipping_violations():
            if order.is_shipment_delayed(cls.SHIPPING_LIMIT_HOURS):
                shipping.append(order)

        return {
            "processing_violations": processing,
            "shipping_violations": shipping,
        }
