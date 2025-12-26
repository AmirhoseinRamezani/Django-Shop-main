from django.db import transaction
from django.core.exceptions import ValidationError
from .models import OrderModel, OrderItemModel, SaleType
from .policies import OrderPolicy
from decimal import Decimal

class OrderService:
    """
    Responsible for creating orders.
    Business rules live here, NOT in views.
    """
    
    @staticmethod
    @transaction.atomic
    def create_online_order(*, user, address, cart, coupon=None):
        # ---- Permission check ----
        OrderPolicy.can_create_order(user)

        # ---- Cart validation ----
        if not cart.cart_items.exists():
            raise ValidationError("سبد خرید خالی است")
        if coupon and not coupon.is_valid():
            raise ValidationError("کد تخفیف معتبر نیست")
        
        # ---- Calculate total price ----
        # total_price = cart.calculate_total_price()

        # ---- Calculate total price ----
        total_price = Decimal(0)
        for item in cart.cart_items.select_related("product"):
            total_price += item.quantity * item.product.final_price
            
        # ---- Create order ----    
        order = OrderModel.objects.create(
            user=user,
            sale_type=SaleType.ONLINE,
            total_price=total_price,

            # snapshot user info
            full_name=user.profile.get_fullname(),
            phone=user.profile.phone_number,
            email=user.email,

            # snapshot address
            address=address.address,
            city=address.city,
            state=address.state,
            zip_code=address.zip_code,

            # coupon relation
            coupon=coupon,
            
            # coupon snapshot (VERY IMPORTANT)
            coupon_code=coupon.code if coupon else None,
            coupon_discount_percent=coupon.discount_percent if coupon else None,
        )

        # ---- Create order items ----
        for item in cart.cart_items.select_related("product"):
            OrderItemModel.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.final_price,
            )


        return order
