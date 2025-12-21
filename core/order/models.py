from django.db import models
from django.conf import settings
from decimal import Decimal


class SaleType(models.TextChoices):
    ONLINE = "ONLINE", "فروش آنلاین"


class OrderStatusType(models.IntegerChoices):
    pending = 1, "در انتظار پرداخت"
    success = 2, "موفق"
    failed = 3, "ناموفق"


class CouponModel(models.Model):
    code = models.CharField(max_length=50, unique=True)
    discount_percent = models.PositiveSmallIntegerField()
    max_limit_usage = models.PositiveIntegerField(default=1)
    expiration_date = models.DateTimeField(null=True, blank=True)
    used_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="used_coupons"
    )

    def __str__(self):
        return self.code


class UserAddressModel(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="addresses"
    )
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.user} - {self.city}"


class OrderModel(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders"
    )

    sale_type = models.CharField(
        max_length=20,
        choices=SaleType.choices,
        default=SaleType.ONLINE
    )

    status = models.IntegerField(
        choices=OrderStatusType.choices,
        default=OrderStatusType.pending
    )

    total_price = models.DecimalField(max_digits=12, decimal_places=0)

    # snapshot buyer
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    email = models.EmailField()

    # snapshot address
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=20)

    coupon = models.ForeignKey(
        CouponModel,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    payment = models.OneToOneField(
        "payment.PaymentModel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order"
    )

    created_date = models.DateTimeField(auto_now_add=True)

    def get_price(self):
        if self.coupon:
            return int(
                self.total_price * (100 - self.coupon.discount_percent) / 100
            )
        return int(self.total_price)

    def __str__(self):
        return f"Order #{self.id}"


class OrderItemModel(models.Model):
    order = models.ForeignKey(
        OrderModel,
        on_delete=models.CASCADE,
        related_name="order_items"
    )
    product = models.ForeignKey(
        "shop.ProductModel",
        on_delete=models.PROTECT
    )
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=12, decimal_places=0)

    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product} x {self.quantity} (Order #{self.order_id})"
