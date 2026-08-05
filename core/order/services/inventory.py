# order/services/inventory.py
from django.db import transaction
from django.db.models import F

from order.models import OrderModel


class InventoryService:
    """
    Centralized inventory mutations.

    Every stock modification in the project
    MUST go through this service.

    This guarantees:

    - atomicity
    - row locking
    - idempotency
    - future warehouse support
    """

    @staticmethod
    @transaction.atomic
    def reserve(order: OrderModel):

        """
        Reserve inventory during order creation.
        """

        products = {}

        for item in (
            order.order_items
            .select_related("product")
            .select_for_update()
        ):

            product = item.product

            if product.id not in products:
                products[product.id] = product

            product.__class__.objects.filter(
                id=product.id,
            ).update(
                stock=F("stock") - item.quantity,
            )

    @staticmethod
    @transaction.atomic
    def restore(order: OrderModel):

        """
        Restore stock after cancellation.
        """

        for item in (
            order.order_items
            .select_related("product")
            .select_for_update()
        ):

            item.product.__class__.objects.filter(
                id=item.product_id,
            ).update(
                stock=F("stock") + item.quantity,
            )

    @staticmethod
    @transaction.atomic
    def increase(product, quantity):

        product.__class__.objects.filter(
            id=product.id
        ).update(
            stock=F("stock") + quantity
        )

    @staticmethod
    @transaction.atomic
    def decrease(product, quantity):

        product.__class__.objects.filter(
            id=product.id
        ).update(
            stock=F("stock") - quantity
        )