# order/services/monitoring.py

from order.models import (
    OrderModel,
    OrderStatusType,
)

def stuck_processing_orders():

    return OrderModel.objects.filter(
        status=OrderStatusType.processing
    )

def delayed_shipments():

    return OrderModel.objects.filter(
        status=OrderStatusType.paid
    )