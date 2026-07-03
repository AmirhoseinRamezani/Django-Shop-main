# order/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.utils.translation import gettext_lazy as _
from payment.models import PaymentStatusType

class SaleType(models.TextChoices):
    ONLINE = "ONLINE", _("Online")


class OrderStatusType(models.IntegerChoices):

    # ---- Payment Phase ----
    pending = 1, _("Pending Payment")
    failed = 2, _("Payment Failed")

    # ---- Paid & Processing ----
    paid = 3, _("Paid")
    processing = 4, _("Processing")

    # ---- Logistics ----
    shipped = 5, _("Shipped")
    delivered = 6, _("Delivered")

    # ---- Return Flow ----
    return_requested = 7, _("Return Requested")
    returned = 8, _("Returned")
    refunded = 9, _("Refunded")

    # ---- Terminal ----
    cancelled = 10, _("Cancelled")

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
        default=OrderStatusType.pending,
        db_index=True,
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

    
    # ---- Coupon Snapshot ----
    coupon_code = models.CharField(max_length=50, null=True, blank=True)
    coupon_discount_percent = models.PositiveIntegerField(null=True, blank=True)
    
    created_date = models.DateTimeField(auto_now_add=True)
    expire_at = models.DateTimeField(db_index=True,help_text="Order expiration time for unpaid orders")
    
    

    # ----- Aging Helpers -----

    def age(self):
        return timezone.now() - self.created_date

    def hours_since_creation(self):
        return self.age().total_seconds() / 3600

    def is_stuck_in_processing(self, max_hours=24):
        return (
            self.status == OrderStatusType.processing
            and self.hours_since_creation() > max_hours
        )

    def is_shipment_delayed(self, max_hours=48):
        return (
            self.status == OrderStatusType.paid
            and self.hours_since_creation() > max_hours
        )
    # ------------------
    # Domain Logic
    # ------------------
    
    def is_expired(self) -> bool:
        return self.expire_at <= timezone.now()

    @property
    def is_payable(self) -> bool:
        return (
            self.status == OrderStatusType.pending
            and not self.is_expired()
        )
    
    # def can_retry_payment(self) -> bool:
    #     """
    #     Payment retry rules:
    #     - success → NEVER retry
    #     - pending / failed → retry allowed
    #     """
    #     return (
    #         not self.is_expired()
    #         and self.status in {
    #             OrderStatusType.pending,
    #             OrderStatusType.failed,
    #         }
    #     )
    def can_refund(self) -> bool:
        return self.status in {
            OrderStatusType.paid,
            OrderStatusType.returned,
        }

    def get_price(self):
        """
        Final payable price after applying coupon.
        This is the ONLY official pricing method.
        """
        total = self.total_price
        if self.coupon_discount_percent:
            return round(
                total * (100 - self.coupon_discount_percent) / 100
            )

        return total
    
    # ---- Payments ----
    def last_payment(self):
        """
        Returns latest payment attempt (if any)
        """
        return self.payments.order_by("-created_date").first()

    def has_pending_payment(self) -> bool:
        """
        Prevent duplicate gateway redirects
        """
        return self.payments.filter(
            status = PaymentStatusType.pending  # OrderStatusType.pending
        ).exists()

    def mark_failed(self):
        """
        Centralized failure handling
        """
        self.status = OrderStatusType.failed
        self.save(update_fields=["status"])
    
    def __str__(self):
        return f"Order #{self.id}"

    # def can_start_payment(self):
    #     return (
    #         not self.is_expired()
    #         and self.status in {
    #             OrderStatusType.pending,
    #             OrderStatusType.failed,
    #         }
    #     )
    
    @property
    def is_paid(self) -> bool:
        return self.status == OrderStatusType.paid

    @property
    def is_completed(self) -> bool:
        return self.status in {
            OrderStatusType.delivered,
            OrderStatusType.refunded,
            OrderStatusType.cancelled,
        }

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
