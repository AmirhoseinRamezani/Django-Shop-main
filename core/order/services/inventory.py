# core/order/services/inventory.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from order.models import (
    InventoryReservation,
    InventoryReservationStatus,
    OrderModel,
)
from shop.models import ProductModel


class InventoryService:
    """
    Canonical inventory mutation service.

    Inventory semantics for Payment V1:

        Product.stock
            = currently sellable/available stock

        InventoryReservation
            = authoritative reservation ledger

    Reservation consumes Product.stock immediately.
    Cancellation restores Product.stock exactly once.

    reserved_stock is intentionally not mutated by this service in V1.
    It is not part of the authoritative reservation accounting yet.
    """

    @staticmethod
    @transaction.atomic
    def reserve(order: OrderModel) -> None:
        """
        Reserve inventory for every OrderItem exactly once.

        Guarantees:
        - Order is locked first.
        - Product locks are acquired in deterministic product-id order.
        - Every reservation is created exactly once.
        - Stock can never become negative.
        - Partial reservation is rolled back atomically.
        - Repeating reserve() is idempotent for an existing reservation.
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

        product_ids = sorted(
            {
                item.product_id
                for item in items
            }
        )

        products = (
            ProductModel.objects
            .select_for_update()
            .filter(pk__in=product_ids)
            .order_by("id")
            .in_bulk()
        )

        for item in items:
            if item.quantity <= 0:
                raise ValidationError(
                    _("Inventory quantity must be positive.")
                )

            product = products.get(item.product_id)

            if product is None:
                raise ValidationError(
                    _("Product does not exist.")
                )

            reservation = (
                InventoryReservation.objects
                .filter(order_item_id=item.id)
                .first()
            )

            if reservation is not None:
                if (
                    reservation.status
                    != InventoryReservationStatus.RESERVED
                ):
                    raise ValidationError(
                        _("Inventory reservation was already released.")
                    )

                if reservation.quantity != item.quantity:
                    raise ValidationError(
                        _("Inventory reservation quantity mismatch.")
                    )

                continue

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
                    _(
                        "Insufficient inventory for product "
                        f"«{product.title}»."
                    )
                )

            InventoryReservation.objects.create(
                order_item_id=item.id,
                quantity=item.quantity,
                status=InventoryReservationStatus.RESERVED,
            )

    @staticmethod
    @transaction.atomic
    def restore(order: OrderModel) -> bool:
        """
        Release every active inventory reservation exactly once.

        The reservation state transition is performed with a conditional
        UPDATE. This UPDATE is the concurrency authority for the release.

        Returns:
            True:
                At least one reservation was successfully claimed and
                released by this transaction.

            False:
                No RESERVED reservation could be claimed by this
                transaction because another transaction had already
                released them.
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

        released_any = False

        for reservation in reservations:
            if reservation.status != InventoryReservationStatus.RESERVED:
                continue

            """
            Atomically claim the reservation.

            Do not rely only on the in-memory status or model.save().
            The conditional UPDATE guarantees that exactly one concurrent
            transaction can transition RESERVED -> RELEASED.
            """

            released_at = timezone.now()

            claimed = (
                InventoryReservation.objects
                .filter(
                    pk=reservation.pk,
                    status=InventoryReservationStatus.RESERVED,
                    released_at__isnull=True,
                )
                .update(
                    status=InventoryReservationStatus.RELEASED,
                    released_at=released_at,
                )
            )

            if claimed != 1:
                continue

            product_id = reservation.order_item.product_id

            product = (
                ProductModel.objects
                .select_for_update()
                .get(pk=product_id)
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
                    _("Failed to restore inventory.")
                )

            released_any = True

        return released_any

    @staticmethod
    @transaction.atomic
    def increase(
        product: ProductModel,
        quantity: int,
    ) -> None:
        """
        Increase sellable stock atomically.
        """

        if quantity <= 0:
            raise ValidationError(
                _("Inventory quantity must be positive.")
            )

        updated = (
            ProductModel.objects
            .filter(pk=product.pk)
            .update(
                stock=F("stock") + quantity,
            )
        )

        if updated != 1:
            raise ValidationError(
                _("Product does not exist.")
            )

    @staticmethod
    @transaction.atomic
    def decrease(
        product: ProductModel,
        quantity: int,
    ) -> None:
        """
        Decrease sellable stock atomically.

        The conditional UPDATE is the concurrency authority.
        No application-level read/modify/write is used.
        """

        if quantity <= 0:
            raise ValidationError(
                _("Inventory quantity must be positive.")
            )

        updated = (
            ProductModel.objects
            .filter(
                pk=product.pk,
                stock__gte=quantity,
            )
            .update(
                stock=F("stock") - quantity,
            )
        )

        if updated != 1:
            raise ValidationError(
                _("Insufficient inventory.")
            )

