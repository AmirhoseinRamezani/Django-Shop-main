# order/services/metrics.py

from django.db.models import Count

from order.models import (
    OrderModel,
    OrderStatusType,
)


def order_status_breakdown():

    return (
        OrderModel.objects
        .values("status")
        .annotate(total=Count("id"))
        .order_by("status")
    )


def active_orders_count():

    return OrderModel.objects.filter(
        status__in=[
            OrderStatusType.paid,
            OrderStatusType.processing,
            OrderStatusType.shipped,
        ]
    ).count()


def refund_rate():

    total = OrderModel.objects.count()

    if total == 0:
        return 0

    refunded = (
        OrderModel.objects
        .filter(status=OrderStatusType.refunded)
        .count()
    )

    return round(refunded / total, 4)