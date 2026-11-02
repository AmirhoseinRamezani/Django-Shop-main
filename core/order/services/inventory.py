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
from order.services.coupon import CouponService
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
                if reservation.status == InventoryReservationStatus.RELEASED:
                    raise ValidationError(
                        _("Inventory reservation was already released.")
                    )

                if reservation.status == InventoryReservationStatus.CONSUMED:
                    raise ValidationError(
                        _("Inventory reservation was already consumed.")
                    )
                if reservation.status != InventoryReservationStatus.RESERVED:
                    raise ValidationError(
                        _("Invalid inventory reservation state.")
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
        Release active reservations exactly once when payment evidence permits.

        Lock order:
            Order -> Payment -> PaymentAttempt -> InventoryReservation
            -> Product (ascending PK)
        """
        locked_order = (
            OrderModel.objects
            .select_for_update()
            .get(pk=order.pk)
        )

        # Unknown provider outcomes retain inventory. This helper locks
        # Payment and PaymentAttempt rows after the Order row.
        if CouponService.has_unresolved_payment_outcome(locked_order):
            return 0

        # A canonical PAID event backed by a consumed successful Payment and
        # its exact successful Attempt makes inventory irreversible. Do not
        # rely on Order.status: the event and financial aggregate are evidence.
        if InventoryService._has_canonical_paid_payment(locked_order):
            return 0

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
            return 0

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

        released_count = 0

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

            if reservation.release():
                released_count += 1

        return released_count

    @staticmethod
    @transaction.atomic
    def consume(order: OrderModel):
        """
        Permanently consume all active reservations owned by this Order.

        Consumption changes reservation state only: stock was deducted at
        reservation time and must never be decremented again.

        Lock order:
            Order -> Payment -> PaymentAttempt -> InventoryReservation
        The canonical payment finalizer already owns Payment and Attempt
        locks before invoking this method.
        """
        locked_order = (
            OrderModel.objects
            .select_for_update()
            .get(pk=order.pk)
        )

        items = list(
            locked_order.order_items
            .order_by("product_id", "pk")
        )
        if not items:
            return 0

        items_by_id = {item.pk: item for item in items}
        reservations = list(
            InventoryReservation.objects
            .select_for_update()
            .filter(order_item__order_id=locked_order.pk)
            .select_related("order_item")
            .order_by("order_item__product_id", "order_item_id", "pk")
        )

        consumed_count = 0
        for reservation in reservations:
            item = items_by_id.get(reservation.order_item_id)
            if item is None:
                raise ValidationError(
                    _("Inventory reservation does not belong to this Order.")
                )

            if reservation.quantity != item.quantity:
                raise ValidationError(
                    _("Inventory reservation quantity mismatch.")
                )

            if reservation.status == InventoryReservationStatus.CONSUMED:
                continue

            if reservation.status != InventoryReservationStatus.RESERVED:
                raise ValidationError(
                    _("Released inventory cannot be consumed.")
                )

            if reservation.consume():
                consumed_count += 1

        return consumed_count

    @staticmethod
    def _has_canonical_paid_payment(order: OrderModel) -> bool:
        """Return true only for a PAID event backed by its exact consumed Payment."""
        from order.events.order_event import OrderEventType
        from payment.enums import PaymentAttemptStatus, PaymentStatusType
        from payment.models import PaymentAttempt, PaymentModel

        paid_events = order.events.filter(
            type=OrderEventType.PAID,
        ).order_by("-id")

        for event in paid_events:
            payload = event.payload if isinstance(event.payload, dict) else {}
            payment_id = payload.get("payment_id")
            attempt_id = payload.get("attempt_id")

            if type(payment_id) is not int or type(attempt_id) is not int:
                continue

            payment = PaymentModel.objects.filter(
                pk=payment_id,
                order_id=order.pk,
                status=PaymentStatusType.SUCCESS,
                is_consumed=True,
            ).first()
            if payment is None:
                continue

            if PaymentAttempt.objects.filter(
                pk=attempt_id,
                payment_id=payment.pk,
                status=PaymentAttemptStatus.SUCCESS,
            ).exists():
                return True

        return False

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