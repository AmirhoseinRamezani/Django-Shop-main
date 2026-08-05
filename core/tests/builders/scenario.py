# tests/builders/scenario_builder.py
from dataclasses import dataclass

from accounts.models import User

from cart.models import CartModel

from order.models import OrderModel

from payment.models import PaymentModel

from shop.models import ProductModel

from order.models import UserAddressModel

from order.models import CouponModel


@dataclass(slots=True)
class Scenario:

    user: User

    address: UserAddressModel

    cart: CartModel

    product: ProductModel | None = None

    coupon: CouponModel | None = None

    order: OrderModel | None = None

    payment: PaymentModel | None = None