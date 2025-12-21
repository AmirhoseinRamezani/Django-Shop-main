from django.db import transaction
from django.core.exceptions import ValidationError
from .models import OrderModel, OrderItemModel, SaleType
from .policies import OrderPolicy


class OrderService:

    @staticmethod
    @transaction.atomic
    def create_online_order(*, user, address, cart, coupon=None):
        OrderPolicy.can_create_order(user)

        if not cart.cart_items.exists():
            raise ValidationError("سبد خرید خالی است")

        total_price = cart.calculate_total_price()

        order = OrderModel.objects.create(
            user=user,
            sale_type=SaleType.ONLINE,
            total_price=total_price,

            full_name=user.profile.get_fullname(),
            phone=user.profile.phone_number,
            email=user.email,

            address=address.address,
            city=address.city,
            state=address.state,
            zip_code=address.zip_code,

            coupon=coupon
        )

        for item in cart.cart_items.select_related("product"):
            OrderItemModel.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.final_price
            )

        if coupon:
            coupon.used_by.add(user)

        return order
