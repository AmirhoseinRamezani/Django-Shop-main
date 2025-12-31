# order/services/create_order.py

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.db.models import F

from order.models import OrderModel, OrderItemModel, OrderStatusType
from shop.models import ProductModel



RESERVATION_MINUTES = 5


class OrderCreationError(Exception):
    pass


def create_order(user, product_id, quantity=1):
    """
    Atomically:
    - lock product
    - reserve stock
    - create order with expiration time
    """

    expire_at = timezone.now() + timedelta(minutes=RESERVATION_MINUTES)

    with transaction.atomic():
        # 🔒 قفل محصول
        product = (
            ProductModel.objects
            .select_for_update()
            .filter(id=product_id, stock__gte=quantity)
            .first()
        )

        if not product:
            raise OrderCreationError("Product is no longer available")

        # 1️⃣ کسر موجودی (رزرو)
        product.stock = F("stock") - quantity
        product.save(update_fields=["stock"])

        # 2️⃣ ایجاد سفارش
        order = OrderModel.objects.create(
            user=user,
            status=OrderStatusType.pending,
            expire_at=expire_at,
        )

        # 3️⃣ آیتم سفارش
        OrderItemModel.objects.create(
            order=order,
            product=product,
            quantity=quantity,
        )

    return order
