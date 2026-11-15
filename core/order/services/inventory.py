# order/services/inventory.py
from django.db import transaction
from django.db.models import F
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.translation import gettext as _

from order.models import (
    InventoryReservation,
    InventoryReservationStatus,
    OrderModel,
)
from order.services.coupon import CouponService
from shop.models import ProductModel


# Capability is intentionally private to this module. Only the canonical
# payment finalizer imports it and can authorize reservation consumption.
_CONSUME_AUTHORIZATION = object()


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

        Every OrderItem must have exactly one matching reservation. All
        reservation and product invariants are validated before the first
        stock mutation, so corrupted reservation data cannot over-credit stock.

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
        # its exact successful Attempt makes inventory irreversible.
        if InventoryService._has_canonical_paid_payment(locked_order):
            return 0

        items = list(
            locked_order.order_items
            .only("pk", "product_id", "quantity")
            .order_by("product_id", "pk")
        )
        reservations = list(
            InventoryReservation.objects
            .select_for_update()
            .filter(order_item__order_id=locked_order.pk)
            .select_related("order_item")
            .order_by("order_item__product_id", "order_item_id", "pk")
        )

        items_by_id = {item.pk: item for item in items}
        if len(items_by_id) != len(items) or len(reservations) != len(items):
            raise ValidationError(
                _("Order inventory reservations are incomplete or duplicated.")
            )

        restore_quantities = {}
        reservation_states = set()
        for reservation in reservations:
            reservation_states.add(reservation.status)
            item = items_by_id.get(reservation.order_item_id)
            if item is None:
                raise ValidationError(
                    _("Inventory reservation does not belong to this Order.")
                )
            if reservation.quantity != item.quantity:
                raise ValidationError(
                    _("Inventory reservation quantity mismatch.")
                )
            if reservation.status not in (
                InventoryReservationStatus.RESERVED,
                InventoryReservationStatus.RELEASED,
                InventoryReservationStatus.CONSUMED,
            ):
                raise ValidationError(_("Invalid inventory reservation state."))

            if reservation.status == InventoryReservationStatus.RESERVED:
                restore_quantities[item.product_id] = (
                    restore_quantities.get(item.product_id, 0)
                    + reservation.quantity
                )

        if (
            InventoryReservationStatus.RESERVED in reservation_states
            and len(reservation_states) > 1
        ):
            raise ValidationError(
                _("Order inventory reservations have inconsistent lifecycle states.")
            )

        if not restore_quantities:
            return 0

        products = (
            ProductModel.objects
            .select_for_update()
            .filter(pk__in=sorted(restore_quantities))
            .order_by("pk")
            .in_bulk()
        )

        # Preflight the complete restore before changing any Product or
        # Reservation. PositiveIntegerField is bounded by PostgreSQL's
        # signed 32-bit integer range.
        max_stock_value = 2_147_483_647
        for product_id, quantity in restore_quantities.items():
            product = products.get(product_id)
            if product is None:
                raise ValidationError(_("Order product no longer exists."))
            if product.stock > max_stock_value - quantity:
                raise ValidationError(
                    _("Restoring inventory would exceed the product stock capacity.")
                )

        for product_id, quantity in restore_quantities.items():
            updated = ProductModel.objects.filter(
                pk=product_id,
                stock__lte=max_stock_value - quantity,
            ).update(stock=F("stock") + quantity)
            if updated != 1:
                raise ValidationError(_("Unable to restore inventory."))

        released_count = 0
        for reservation in reservations:
            if reservation.status == InventoryReservationStatus.RESERVED:
                if reservation.release():
                    released_count += 1

        return released_count

    @staticmethod
    @transaction.atomic
    def consume(order: OrderModel, *, _authorization=None):
        """
        Permanently consume all active reservations owned by this Order.

        Consumption changes reservation state only: stock was deducted at
        reservation time and must never be decremented again.

        This operation is restricted to confirm_order_payment() through a
        module-private capability. Calling it from any other application path
        is rejected before acquiring or mutating database rows.

        Lock order:
            Order -> Payment -> PaymentAttempt -> InventoryReservation
        The canonical payment finalizer already owns Payment and Attempt
        locks before invoking this method.
        """
        if _authorization is not _CONSUME_AUTHORIZATION:
            raise PermissionDenied(
                "Inventory consumption is only allowed during canonical payment finalization."
            )

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

        # Payment success must never finalize an Order with missing or
        # mismatched inventory evidence. Validate the full set before changing
        # any reservation so the caller's financial transaction can roll back
        # cleanly on inconsistency.
        if len(reservations) != len(items):
            raise ValidationError(
                _("Order inventory reservations are incomplete or duplicated.")
            )

        reservation_item_ids = {
            reservation.order_item_id
            for reservation in reservations
        }
        if reservation_item_ids != set(items_by_id):
            raise ValidationError(
                _("Order inventory reservations do not match Order items.")
            )

        for reservation in reservations:
            item = items_by_id[reservation.order_item_id]

            if reservation.quantity != item.quantity:
                raise ValidationError(
                    _("Inventory reservation quantity mismatch.")
                )

            if reservation.status not in (
                InventoryReservationStatus.RESERVED,
                InventoryReservationStatus.CONSUMED,
            ):
                raise ValidationError(
                    _("Released inventory cannot be consumed.")
                )

        consumed_count = 0
        for reservation in reservations:
            if reservation.status == InventoryReservationStatus.CONSUMED:
                continue

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