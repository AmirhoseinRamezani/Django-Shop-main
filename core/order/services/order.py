
from decimal import Decimal
from datetime import timedelta

from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone

from shop.constants import ProductStatusType
from shop.models import ProductModel

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
        
        cart_items = (
            cart.cart_items
            .select_related("product")
            .select_for_update()
        )
        
        product_ids = [item.product_id for item in cart_items]
        
        products = (
            ProductModel.objects
            .select_for_update()
            .filter(id__in=product_ids)
            .in_bulk()
        )

        
        for item in cart_items:
            product = products[item.product_id]

            # وضعیت فروش
            if product.status != ProductStatusType.PUBLISH:
                raise ValidationError(
                    f"محصول «{product.title}» قابل فروش نیست"
                )

            # موجودی
            if product.stock < item.quantity:
                raise ValidationError(
                    f"موجودی محصول «{product.title}» کافی نیست"
                )

            total_price += item.quantity * product.final_price
        # for item in cart.cart_items.select_related("product"):
        #     total_price += item.quantity * item.product.final_price
        # ⏳ Order expiration window (payment time limit)
        expire_at = timezone.now() + timedelta(hours=2)
        
        order = OrderModel.objects.create(
            user=user,
            sale_type=SaleType.ONLINE,
            status=OrderStatusType.pending,
            total_price=total_price,
            expire_at=expire_at,

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

        # items = [
        #     OrderItemModel(
        #         order=order,
        #         product=item.product,
        #         quantity=item.quantity,
        #         price=item.product.final_price,
        #     )
        #     for item in cart.cart_items.select_related("product")
        # ]
        # OrderItemModel.objects.bulk_create(items)
        order_items = []
        for item in cart_items:
            product = products[item.product_id]

            product.stock = F("stock") - item.quantity
            product.save(update_fields=["stock"])

            order_items.append(
                OrderItemModel(
                    order=order,
                    product=product,
                    quantity=item.quantity,
                    price=product.final_price,
                )
            )

        OrderItemModel.objects.bulk_create(order_items)

        return order
    