# order/services/pricing.py
from decimal import Decimal, ROUND_DOWN

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from shop.constants import ProductStatusType


class OrderPricingService:
    """Server-side pricing primitives for the Order financial snapshot."""

    @staticmethod
    def calculate(cart_items, products):
        """Return item subtotal after product discounts, before coupon discount."""
        total = Decimal("0")

        for item in cart_items:

            product = products[item.product_id]

            if product.status != ProductStatusType.PUBLISH:
                raise ValidationError(_("Product is unavailable"))

            if product.stock < item.quantity:
                raise ValidationError(_("Insufficient inventory"))

            total += Decimal(str(product.final_price)) * item.quantity

        return total

    @staticmethod
    def discounted_subtotal(subtotal_price, discount_percent):
        """Apply a percentage coupon using the project's integer-unit truncation rule."""
        subtotal = Decimal(str(subtotal_price))
        percent = Decimal(str(discount_percent))
        if subtotal < 0:
            raise ValidationError(_("Subtotal cannot be negative"))
        if percent < 0 or percent > 100:
            raise ValidationError(_("Coupon discount percentage is invalid"))

        discounted = (
            subtotal * (Decimal("100") - percent) / Decimal("100")
        ).to_integral_value(rounding=ROUND_DOWN)

        # Defend the financial boundary even if invalid data bypasses model validation.
        return min(max(discounted, Decimal("0")), subtotal)

    @staticmethod
    def calculate_tax(*, subtotal_price, discount_amount, shipping_price):
        """V1 tax boundary: no authoritative tax policy is configured, so tax is zero."""
        # Keep the inputs explicit so a verified tax policy can be introduced here later.
        return Decimal("0")