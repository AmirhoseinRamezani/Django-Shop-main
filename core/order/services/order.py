from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError

from order.models import (
    OrderModel,
    OrderItemModel,
    SaleType,
    OrderStatusType,
)
from order.policies import OrderPolicy


class OrderService:
    """
    Canonical order creation logic.
    No gateway. No session. No side effects.
    """

    @staticmethod
    @transaction.atomic
    def create_online_order(*, user, address, cart, coupon=None):
        OrderPolicy.can_create_order(user)

        if not cart.cart_items.exists():
            raise ValidationError("سبد خرید خالی است")

        if coupon and not coupon.is_valid():
            raise ValidationError("کد تخفیف معتبر نیست")

        total_price = Decimal("0")
        for item in cart.cart_items.select_related("product"):
            total_price += item.quantity * item.product.final_price

        order = OrderModel.objects.create(
            user=user,
            sale_type=SaleType.ONLINE,
            status=OrderStatusType.pending,
            total_price=total_price,

            # user snapshot
            full_name=user.profile.get_fullname(),
            phone=user.profile.phone_number,
            email=user.email,

            # address snapshot
            address=address.address,
            city=address.city,
            state=address.state,
            zip_code=address.zip_code,

            # coupon snapshot
            coupon=coupon,
            coupon_code=coupon.code if coupon else None,
            coupon_discount_percent=coupon.discount_percent if coupon else None,
        )

        items = [
            OrderItemModel(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.final_price,
            )
            for item in cart.cart_items.select_related("product")
        ]
        OrderItemModel.objects.bulk_create(items)

        return order
