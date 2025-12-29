from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
from django.core.exceptions import ValidationError

class SaleType(models.TextChoices):
    ONLINE = "ONLINE", "فروش آنلاین"


class OrderStatusType(models.IntegerChoices):
    pending = 1, "در انتظار پرداخت"
    success = 2, "موفق"
    failed = 3, "ناموفق"
    cancelled = 4, "لغو شده"
    refunded = 5, "مرجوع شده"

class CouponModel(models.Model):
    """
    Coupon model
    - Validation is separated from consumption
    - Consumed ONLY after successful payment
    """

    code = models.CharField(max_length=50, unique=True)
    discount_percent = models.PositiveSmallIntegerField()

    # Usage control
    max_limit_usage = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)

    # Optional expiration
    expiration_date = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_date"]
        
    def is_valid(self):
        """
        Check if coupon can be applied (NO consumption here)
        Used in checkout / validation step
        """
        if not self.is_active:
            return False

        if self.used_count >= self.max_limit_usage:
            return False

        if self.expiration_date and self.expiration_date < timezone.now():
            return False

        return True

    def mark_used(self):
        """
        Consume coupon AFTER successful payment
        Must be called inside transaction
        """
        self.used_count += 1
        self.save(update_fields=["used_count"])

    def rollback(self):
        """
        Rollback coupon usage if payment fails
        (Normally not needed if VerifyView is correct,
        but kept for safety)
        """
        if self.used_count > 0:
            self.used_count -= 1
            self.save(update_fields=["used_count"])

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
        on_delete=models.SET_NULL,
        related_name="orders",
    )

    payment = models.OneToOneField(
        "payment.PaymentModel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order",
    )
    # ---- Coupon Snapshot ----
    coupon_code = models.CharField(max_length=50, null=True, blank=True)
    coupon_discount_percent = models.PositiveIntegerField(null=True, blank=True)
    
    created_date = models.DateTimeField(auto_now_add=True)
    expire_at = models.DateTimeField(db_index=True)
    
    def can_retry_payment(self) -> bool:
        """
        Payment retry rules:
        - success → NEVER retry
        - pending / failed → retry allowed
        """
        return self.status in {
            OrderStatusType.pending,
            OrderStatusType.failed,
        }
    def can_refund(self) -> bool:
        return self.status == OrderStatusType.success

    def get_price(self):
        total = self.total_price
        if self.coupon_discount_percent:
            return round(
                total * (100 - self.coupon_discount_percent) / 100
            )

        return total

    def is_expired(self):
        return self.expire_at < timezone.now()
    
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
