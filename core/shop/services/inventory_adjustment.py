from __future__ import annotations

import hashlib
import json
from typing import Final

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils.translation import gettext as _

from shop.models import (
    InventoryAdjustment,
    InventoryAdjustmentDirection,
    ProductModel,
)


class InventoryAdjustmentService:
    """The sole application-level boundary for manual Product.stock changes."""

    permission_codename: Final[str] = "shop.adjust_product_stock"
    max_stock_value: Final[int] = 2_147_483_647

    @classmethod
    @transaction.atomic
    def adjust(
        cls,
        *,
        product_id: int,
        actor,
        direction: str,
        quantity: int,
        reason: str,
        idempotency_key: str,
    ) -> InventoryAdjustment:
        cls._authorize(actor)

        product_id = cls._positive_integer(product_id, "product_id")
        quantity = cls._positive_integer(quantity, "quantity")
        direction = cls._validate_direction(direction)
        reason = cls._validate_reason(reason)
        idempotency_key = cls._validate_idempotency_key(idempotency_key)

        fingerprint = cls._fingerprint(
            product_id=product_id,
            actor_id=actor.pk,
            direction=direction,
            quantity=quantity,
            reason=reason,
        )

        existing = InventoryAdjustment.objects.filter(
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            return cls._return_existing(existing, fingerprint)

        product = (
            ProductModel.objects
            .select_for_update()
            .get(pk=product_id)
        )

        # Recheck after acquiring the Product lock. This serializes same-product
        # retries while the unique index below arbitrates cross-product key races.
        existing = InventoryAdjustment.objects.filter(
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            return cls._return_existing(existing, fingerprint)

        previous_stock = product.stock
        if direction == InventoryAdjustmentDirection.INCREASE:
            resulting_stock = previous_stock + quantity
            if resulting_stock > cls.max_stock_value:
                raise ValidationError(_("The resulting stock exceeds the supported range."))
        else:
            resulting_stock = previous_stock - quantity
            if resulting_stock < product.reserved_stock:
                raise ValidationError(
                    _("Stock cannot be reduced below the currently reserved quantity.")
                )

        try:
            # Keep the stock delta and its audit row in the same savepoint.
            # A global idempotency-key collision rolls both operations back.
            with transaction.atomic():
                filters = {
                    "pk": product.pk,
                    "stock": previous_stock,
                }
                if direction == InventoryAdjustmentDirection.DECREASE:
                    filters["stock__gte"] = F("reserved_stock") + quantity
                    stock_expression = F("stock") - quantity
                else:
                    stock_expression = F("stock") + quantity

                updated = ProductModel.objects.filter(**filters).update(
                    stock=stock_expression,
                )
                if updated != 1:
                    raise ValidationError(
                        _("Product stock changed or the adjustment violates inventory constraints.")
                    )

                adjustment = InventoryAdjustment(
                    product=product,
                    actor=actor,
                    direction=direction,
                    quantity=quantity,
                    previous_stock=previous_stock,
                    resulting_stock=resulting_stock,
                    reason=reason,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                )
                adjustment._service_write = True
                adjustment.save(force_insert=True)
        except IntegrityError:
            # A concurrent request may have inserted the globally unique key
            # while this transaction held a lock on a different Product.
            existing = InventoryAdjustment.objects.filter(
                idempotency_key=idempotency_key,
            ).first()
            if existing is None:
                raise
            return cls._return_existing(existing, fingerprint)

        return adjustment

    @classmethod
    def _authorize(cls, actor) -> None:
        if (
            actor is None
            or not getattr(actor, "is_authenticated", False)
            or not getattr(actor, "is_active", False)
            or not actor.has_perm(cls.permission_codename)
        ):
            raise PermissionDenied(_("You are not allowed to adjust product stock."))

    @staticmethod
    def _positive_integer(value, field_name: str) -> int:
        if type(value) is not int or value <= 0:
            raise ValidationError({field_name: _("A positive integer is required.")})
        return value

    @staticmethod
    def _validate_direction(direction: str) -> str:
        if direction not in InventoryAdjustmentDirection.values:
            raise ValidationError({"direction": _("Invalid inventory adjustment direction.")})
        return direction

    @staticmethod
    def _validate_reason(reason: str) -> str:
        if not isinstance(reason, str):
            raise ValidationError({"reason": _("A reason is required.")})
        reason = reason.strip()
        if not reason:
            raise ValidationError({"reason": _("A reason is required.")})
        if len(reason) > 10_000:
            raise ValidationError({"reason": _("The reason is too long.")})
        return reason

    @staticmethod
    def _validate_idempotency_key(key: str) -> str:
        if not isinstance(key, str):
            raise ValidationError({"idempotency_key": _("An idempotency key is required.")})
        key = key.strip()
        if not key or len(key) > 128:
            raise ValidationError(
                {"idempotency_key": _("The idempotency key must contain 1 to 128 characters.")}
            )
        return key

    @staticmethod
    def _fingerprint(
        *,
        product_id: int,
        actor_id: int,
        direction: str,
        quantity: int,
        reason: str,
    ) -> str:
        payload = {
            "actor_id": actor_id,
            "direction": direction,
            "product_id": product_id,
            "quantity": quantity,
            "reason": reason,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _return_existing(
        adjustment: InventoryAdjustment,
        fingerprint: str,
    ) -> InventoryAdjustment:
        if adjustment.request_fingerprint != fingerprint:
            raise ValidationError(
                _("The idempotency key has already been used with a different request.")
            )
        return adjustment