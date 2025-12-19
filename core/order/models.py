from django.db import models
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator


class OrderStatusType(models.IntegerChoices):
    pending = 1, "در انتظار پرداخت"
    success = 2, "موفق"
    failed = 3, "ناموفق"
    manual = 4, "ثبت سفارش دستی"


class SaleType(models.IntegerChoices):
    online = 1, "پرداخت آنلاین"
    manual = 2, "ثبت سفارش"


class UserAddressModel(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    address = models.CharField(max_length=250)
    state = models.CharField(max_length=50)
    city = models.CharField(max_length=50)
    zip_code = models.CharField(max_length=50)

    created_date = models.DateTimeField(auto_now_add=True)


class CouponModel(models.Model):
    code = models.CharField(max_length=100, unique=True)
    discount_percent = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    max_limit_usage = models.PositiveIntegerField(default=10)
    used_by = models.ManyToManyField("accounts.User", blank=True)
    expiration_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.code


class OrderModel(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.PROTECT)

    # buyer snapshot
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    email = models.EmailField()

    address = models.CharField(max_length=250)
    state = models.CharField(max_length=50)
    city = models.CharField(max_length=50)
    zip_code = models.CharField(max_length=50)

    sale_type = models.IntegerField(choices=SaleType.choices)
    status = models.IntegerField(
        choices=OrderStatusType.choices,
        default=OrderStatusType.pending
    )

    total_price = models.DecimalField(max_digits=12, decimal_places=0)
    coupon = models.ForeignKey(
        CouponModel, null=True, blank=True, on_delete=models.SET_NULL
    )

    payment = models.OneToOneField(
        "payment.PaymentModel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    created_date = models.DateTimeField(auto_now_add=True)

    def get_payable_price(self):
        if self.coupon:
            return self.total_price - (
                self.total_price * Decimal(self.coupon.discount_percent / 100)
            )
        return self.total_price


class OrderItemModel(models.Model):
    order = models.ForeignKey(
        OrderModel,
        related_name="items",
        on_delete=models.CASCADE
    )
    product = models.ForeignKey("shop.ProductModel", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=0)
