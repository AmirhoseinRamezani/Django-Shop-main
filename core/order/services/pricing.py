# order/services/pricing.py
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from shop.constants import ProductStatusType


class OrderPricingService:

    @staticmethod
    def calculate(cart_items, products):

        total = Decimal("0")

        for item in cart_items:

            product = products[item.product_id]

            if product.status != ProductStatusType.PUBLISH:
                raise ValidationError(
                    _("Product is unavailable")
                )

            if product.stock < item.quantity:
                raise ValidationError(
                    _("Insufficient inventory")
                )

            total += (
                product.final_price *
                item.quantity
            )

        return total