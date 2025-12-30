# order/services/confirm_payment.py

from django.db import transaction
from django.core.exceptions import ValidationError

from order.models import OrderModel, OrderStatusType
from payment.models import PaymentStatusType


def confirm_order_payment(order_id):
    """
    Finalize order after successful payment.
    Atomic & idempotent.
    """
    with transaction.atomic():
        order = (
            OrderModel.objects
            .select_for_update()
            .select_related()
            .get(id=order_id)
        )

        if order.status != OrderStatusType.pending:
            return order

        if order.is_expired():
            raise ValueError("Order expired")

        # Ensure at least one successful payment exists
        if not order.payments.filter(
            status=PaymentStatusType.success
        ).exists():
            raise ValidationError("No successful payment found")

        order.status = OrderStatusType.success
        order.save(update_fields=["status"])

    return order
