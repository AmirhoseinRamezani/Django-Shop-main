# order/services/inventory.py
from django.db import transaction
from django.db.models import F
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from order.models import (
    InventoryReservation,
    InventoryReservationStatus,
    OrderModel,
)
from shop.models import ProductModel


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
        Reserve inventory for every OrderItem exactly once.

        Lock order:
            Order -> InventoryReservation -> Product (ascending PK)
        """
        locked_order = (
            OrderModel.objects
            .select_for_update()
            .get(pk=order.pk)
        )

        items = list(
            locked_order.order_items
            .order_by("product_id", "id")
        )
        if not items:
            return

        item_ids = [item.pk for item in items]
        reservations = {
            reservation.order_item_id: reservation
            for reservation in (
                InventoryReservation.objects
                .select_for_update()
                .filter(order_item_id__in=item_ids)
                .order_by("order_item_id", "pk")
            )
        }

        items_to_reserve = []
        for item in items:
            reservation = reservations.get(item.pk)
            if reservation is not None:
                if reservation.status != InventoryReservationStatus.RESERVED:
                    raise ValidationError(
                        _("Inventory reservation was already released.")
                    )

                if reservation.quantity != item.quantity:
                    raise ValidationError(
                        _("Inventory reservation quantity mismatch.")
                    )
                continue

            if item.quantity <= 0:
                raise ValidationError(
                    _("Inventory quantity must be positive.")
                )

            items_to_reserve.append(item)

        if not items_to_reserve:
            return

        product_ids = sorted({
            item.product_id
            for item in items_to_reserve
        })
        products = (
            ProductModel.objects
            .select_for_update()
            .filter(pk__in=product_ids)
            .order_by("pk")
            .in_bulk()
        )

        for item in items_to_reserve:
            product = products.get(item.product_id)
            if product is None:
                raise ValidationError(
                    _("Order product no longer exists.")
                )

            updated = (
                ProductModel.objects
                .filter(
                    pk=product.pk,
                    stock__gte=item.quantity,
                )
                .update(
                    stock=F("stock") - item.quantity,
                )
            )
            if updated != 1:
                raise ValidationError(
                    _("Insufficient inventory.")
                )

            InventoryReservation.objects.create(
                order_item=item,
                quantity=item.quantity,
            )

    @staticmethod
    @transaction.atomic
    def restore(order: OrderModel):
        """
        Release every active inventory reservation exactly once.

        Product rows are locked in ascending PK order to make the lock
        acquisition order independent of OrderItem insertion order.
        """
        locked_order = (
            OrderModel.objects
            .select_for_update()
            .get(pk=order.pk)
        )

        order_item_count = locked_order.order_items.count()
        reservations = list(
            InventoryReservation.objects
            .select_for_update()
            .filter(order_item__order_id=locked_order.pk)
            .select_related("order_item")
            .order_by("order_item__product_id", "order_item_id", "pk")
        )

        if order_item_count != len(reservations):
            raise ValidationError(
                _("Order inventory reservations are incomplete.")
            )

        if not reservations:
            return

        product_ids = sorted({
            reservation.order_item.product_id
            for reservation in reservations
            if reservation.status == InventoryReservationStatus.RESERVED
        })
        products = (
            ProductModel.objects
            .select_for_update()
            .filter(pk__in=product_ids)
            .order_by("pk")
            .in_bulk()
        )

        for reservation in reservations:
            if reservation.status != InventoryReservationStatus.RESERVED:
                continue

            product = products.get(reservation.order_item.product_id)
            if product is None:
                raise ValidationError(
                    _("Order product no longer exists.")
                )

            updated = (
                ProductModel.objects
                .filter(pk=product.pk)
                .update(
                    stock=F("stock") + reservation.quantity,
                )
            )
            if updated != 1:
                raise ValidationError(
                    _("Unable to restore inventory.")
                )

            reservation.release()

    @staticmethod
    @transaction.atomic
    def increase(product, quantity):
        if quantity <= 0:
            raise ValidationError(_("Inventory quantity must be positive."))

        product.__class__.objects.filter(
            id=product.id
        ).update(
            stock=F("stock") + quantity
        )

    @staticmethod
    @transaction.atomic
    def decrease(product, quantity):
        if quantity <= 0:
            raise ValidationError(_("Inventory quantity must be positive."))

        updated = (
            product.__class__.objects
            .filter(
                id=product.id,
                stock__gte=quantity,
            )
            .update(
                stock=F("stock") - quantity,
            )
        )

        if updated != 1:
            raise ValidationError(_("Insufficient inventory."))