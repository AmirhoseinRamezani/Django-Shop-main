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
        """
        locked_order = (
            OrderModel.objects
            .select_for_update()
            .get(pk=order.pk)
        )

        for item in (
            locked_order.order_items
            .order_by("product_id", "id")
        ):
            reservation = (
                InventoryReservation.objects
                .filter(order_item_id=item.id)
                .first()
            )

            if reservation:
                if reservation.status != InventoryReservationStatus.RESERVED:
                    raise ValidationError(
                        _("Inventory reservation was already released.")
                    )

                if reservation.quantity != item.quantity:
                    raise ValidationError(
                        _("Inventory reservation quantity mismatch.")
                    )

                continue

            product = (
                item.product.__class__.objects
                .select_for_update()
                .get(pk=item.product_id)
            )

            if item.quantity <= 0:
                raise ValidationError(
                    _("Inventory quantity must be positive.")
                )

            updated = (
                item.product.__class__.objects
                .filter(
                    id=product.id,
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
        """
        locked_order = (
            OrderModel.objects
            .select_for_update()
            .get(pk=order.pk)
        )

        reservations = list(
            InventoryReservation.objects
            .select_for_update()
            .filter(order_item__order_id=locked_order.pk)
            .select_related("order_item")
            .order_by("order_item__product_id", "id")
        )

        if locked_order.order_items.exists() and (
            len(reservations) != locked_order.order_items.count()
        ):
            raise ValidationError(
                _("Order inventory reservations are incomplete.")
            )

        for reservation in reservations:
            if reservation.status != InventoryReservationStatus.RESERVED:
                continue

            product = (
                reservation.order_item.product.__class__.objects
                .select_for_update()
                .get(pk=reservation.order_item.product_id)
            )

            product.__class__.objects.filter(
                id=product.id,
            ).update(
                stock=F("stock") + reservation.quantity,
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