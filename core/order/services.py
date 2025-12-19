from order.models import OrderModel, OrderItemModel, SaleType
from cart.models import CartModel


class OrderService:

    @staticmethod
    def create_online_order(user, address, cart, coupon=None):
        order = OrderModel.objects.create(
            user=user,
            full_name=user.get_full_name(),
            phone=user.phone,
            email=user.email,
            address=address.address,
            city=address.city,
            state=address.state,
            zip_code=address.zip_code,
            sale_type=SaleType.online,
            total_price=cart.calculate_total_price(),
            coupon=coupon
        )

        for item in cart.cart_items.all():
            OrderItemModel.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.get_price()
            )

        return order
