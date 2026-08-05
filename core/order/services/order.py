# order/services/order.py
from decimal import Decimal
from datetime import timedelta

from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone

from shop.constants import ProductStatusType
from shop.models import ProductModel

from order.events.order_event import OrderEventType
from order.services.events import record_order_event

from order.services.inventory import InventoryService

from order.models import (
    OrderModel,
    OrderItemModel,
    SaleType,
    OrderStatusType,
)
from order.services.pricing import OrderPricingService

from order.policies import OrderPolicy
from django.utils.translation import gettext as _


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
            raise ValidationError(_("Your shopping cart is empty"))

        if coupon and not coupon.is_valid():
            raise ValidationError(_("Discount code is not valid"))

        
        cart_items = list(
            cart.cart_items
            .select_related("product")
            .select_for_update()
        )

        if not cart_items:
            raise ValidationError(_("Your shopping cart is empty"))
        
        product_ids = [item.product_id for item in cart_items]
        
        products = (
            ProductModel.objects
            .select_for_update()
            .filter(id__in=product_ids)
            .in_bulk()
        )
        # total_price = Decimal("0")
        total_price = OrderPricingService.calculate(
            cart_items,
            products,
        )
        
        for item in cart_items:
            product = products[item.product_id]

            # وضعیت فروش
            if product.status != ProductStatusType.PUBLISH:
                raise ValidationError(_(
                    f"Product «{product.title}» is not for sale"
                ))

            # موجودی
            if product.stock < item.quantity:
                raise ValidationError(_(
                    f"Insufficient inventory for product «{product.title}»"
                ))

            # total_price += item.quantity * product.final_price
            
        # for item in cart.cart_items.select_related("product"):
        #     total_price += item.quantity * item.product.final_price
        # ⏳ Order expiration window (payment time limit)
        
        expire_at = timezone.now() + timedelta(minutes=15)
        
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
        
        #📜 event: order created
        record_order_event(
            order=order,
            type=OrderEventType.CREATED,
            actor=user,
            payload={
                "total_price": str(total_price),
                "expire_at": expire_at.isoformat(),
            },
        )
        order_items = []
        for item in cart_items:
            product = products[item.product_id]

            # ProductModel.objects.filter(
            #     id=product.id
            # ).update(
            #     stock=F("stock") - item.quantity
            # )
            InventoryService.decrease(
                product,
                item.quantity,
            )
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
    