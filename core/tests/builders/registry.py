# tests/builders/registry.py
from tests.factories.accounts import UserFactory
from tests.factories.shop import ProductFactory
from tests.factories.shop import CouponFactory
from tests.factories.shop import AddressFactory
from tests.factories.cart import CartFactory
from tests.factories.cart import CartItemFactory
from tests.factories.order import OrderFactory
from tests.factories.order import OrderItemFactory
from tests.factories.payment import PaymentFactory


class Registry:

    User = UserFactory

    Product = ProductFactory

    Coupon = CouponFactory

    Address = AddressFactory

    Cart = CartFactory

    CartItem = CartItemFactory

    Order = OrderFactory

    OrderItem = OrderItemFactory

    Payment = PaymentFactory