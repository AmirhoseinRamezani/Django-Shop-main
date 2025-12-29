# order/services/confirm_payment.py

from django.db import transaction
from order.models import OrderModel, OrderStatusType


def confirm_order_payment(order_id):
    with transaction.atomic():
        order = (
            OrderModel.objects
            .select_for_update()
            .get(id=order_id)
        )

        if order.status != OrderStatusType.pending:
            return order

        if order.is_expired():
            raise ValueError("Order expired")

        order.status = OrderStatusType.paid
        order.save(update_fields=["status"])

    return order
