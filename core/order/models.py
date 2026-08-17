# order/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
# from payment.models import PaymentStatusType
from payment.enums import PaymentStatusType
from django.db.models import F
from django.db.models import Q


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
    
    discount_percent = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
    )

    # Usage control
    max_limit_usage = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)

    # Optional expiration
    expiration_date = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    discount_percent__gte=0,
                    discount_percent__lte=100,
                ),
                name="coupon_discount_percent_valid",
            ),
            models.CheckConstraint(
                condition=Q(
                    max_limit_usage__gte=0,
                ),
                name="coupon_max_usage_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(
                    used_count__gte=0,
                ),
                name="coupon_used_count_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(
                    used_count__lte=F("max_limit_usage"),
                ),
                name="coupon_used_count_lte_max_usage",
            ),
        ]
        
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
        # if order.coupon:
        # CouponModel.objects.filter(
        #     pk=order.coupon_id
        # ).update(
        #     used_count=F("used_count") + 1
        # )
        # self.used_count =F("used_count") + 1
        # self.save(update_fields=["used_count"])
        """
        Atomically consume one coupon usage.

        Must be called inside transaction.atomic().
        """
        updated = (
            type(self)
            .objects
            .filter(
                pk=self.pk,
                is_active=True,
                used_count__lt=F(
                    "max_limit_usage"
                ),
            )
            .filter(
                Q(expiration_date__isnull=True)
                | Q(
                    expiration_date__gt=timezone.now()
                )
            )
            .update(
                used_count=F("used_count") + 1,
            )
        )

        if updated != 1:
            raise ValidationError(
                _("Coupon is no longer available.")
            )

        self.refresh_from_db(
            fields=[
                "used_count",
                "is_active",
                "max_limit_usage",
                "expiration_date",
            ]
        )

    # def rollback(self):
    #     """
    #     Rollback coupon usage if payment fails
    #     (Normally not needed if VerifyView is correct,
    #     but kept for safety)
    #     """
    #     if self.used_count > 0:
    #         self.used_count -= 1
    #         self.save(update_fields=["used_count"])

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

    total_price = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        validators=[
            MinValueValidator(0),
        ],
        help_text=_(
            "Legacy gross order total."
        ),
    )

    # snapshot buyer
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    email = models.EmailField()

    # paid_date = models.DateTimeField(null=True, blank=True)
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

    # -----------------------------------------
    # Pricing
    # -----------------------------------------

    subtotal_price = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[
            MinValueValidator(0),
        ],
        help_text=_(
            "Total price of order items before discount."
        ),
    )

    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[
            MinValueValidator(0),
        ],
        help_text=_("Total discount applied to the order."),
    )

    shipping_price = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[
            MinValueValidator(0),
        ],
        help_text=_(
            "Shipping cost snapshot."
        ),
    )

    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[
            MinValueValidator(0),
        ],
        help_text=_(
            "Tax amount snapshot."
        ),
    )

    payable_price = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        validators=[
            MinValueValidator(0),
        ],
        help_text=_("Final amount that customer must pay."),
    )

    # -----------------------------------------
    # Lifecycle Dates
    # -----------------------------------------

    paid_date = models.DateTimeField(
        null=True,
        blank=True,
    )

    completed_date = models.DateTimeField(
        null=True,
        blank=True,
    )

    cancelled_date = models.DateTimeField(
        null=True,
        blank=True,
    )
    
    # ---- Coupon Snapshot ----
    coupon_code = models.CharField(max_length=50, null=True, blank=True)
    coupon_discount_percent = models.PositiveIntegerField(null=True, blank=True)
    
    created_date = models.DateTimeField(auto_now_add=True)
    expire_at = models.DateTimeField(db_index=True,help_text="Order expiration time for unpaid orders")
    
    
    class Meta:
        ordering = [
            "-created_date",
        ]
        indexes = [
            models.Index(
                fields=[
                    "status",
                    "expire_at",
                ],
            ),

            models.Index(
                fields=[
                    "user",
                    "-created_date",
                ],
            ),

            models.Index(
                fields=[
                    "paid_date",
                ],
            ),

            models.Index(
                fields=[
                    "completed_date",
                ],
            ),

            models.Index(
                fields=[
                    "cancelled_date",
                ],
            ),
        ]

        constraints = [

            models.CheckConstraint(
                condition=Q(discount_amount__lte=F("subtotal_price")),
                name="discount_less_than_subtotal",
            ),

            # models.CheckConstraint(
            #     condition=(
            #         F("payable_price")
            #         ==
            #         (
            #             F("subtotal_price")
            #             - F("discount_amount")
            #             + F("shipping_price")
            #             + F("tax_amount")
            #         )
            #     ),
            #     name="order_payable_price_consistent",
            # ),

            models.CheckConstraint(
                condition=(
                    (
                        Q(
                            paid_date__isnull=True
                        )
                        & ~Q(
                            status__in=[
                                OrderStatusType.paid,
                                OrderStatusType.processing,
                                OrderStatusType.shipped,
                                OrderStatusType.delivered,
                                OrderStatusType.return_requested,
                                OrderStatusType.returned,
                                OrderStatusType.refunded,
                            ]
                        )
                    )
                    |
                    Q(
                        paid_date__isnull=False
                    )
                ),
                name="order_paid_date_consistent",
            ),
        ]
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


    @property
    def final_price(self):
        """
        Final payable price after applying coupon.
        This is the ONLY official pricing method.
        """
        # total = self.total_price
        # if self.coupon_discount_percent:
        #     total = round(
        #         total *(100 - self.coupon_discount_percent)/ 100
        #     )
        # return total
        return self.payable_price
        
    # def get_price(self):
    #     """
    #     Final payable price after applying coupon.
    #     This is the ONLY official pricing method.
    #     """
    #     total = self.total_price
    #     if self.coupon_discount_percent:
    #         return round(
    #             total * (100 - self.coupon_discount_percent) / 100
    #         )

    #     return total
    
    
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
        
    def mark_paid(self):

        self.status = (
            OrderStatusType.paid
        )

        if self.paid_date is None:
            self.paid_date = (
                timezone.now()
            )

        self.save(
            update_fields=[
                "status",
                "paid_date",
            ]
        )

    def mark_completed(self):

        self.completed_date = (
            timezone.now()
        )

        self.save(
            update_fields=[
                "completed_date",
            ]
        )

    def mark_cancelled(self):

        self.status = (
            OrderStatusType.cancelled
        )

        self.cancelled_date = (
            timezone.now()
        )

        self.save(
            update_fields=[
                "status",
                "cancelled_date",
            ]
        )
    
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
    def is_paid(self):
        return self.status in {
            OrderStatusType.paid,
            OrderStatusType.processing,
            OrderStatusType.shipped,
            OrderStatusType.delivered,
            OrderStatusType.return_requested,
            OrderStatusType.returned,
            OrderStatusType.refunded,
        }

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
    # quantity = models.PositiveIntegerField(default=1)
    # price = models.DecimalField(max_digits=12, decimal_places=0)
    
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[
            MinValueValidator(1),
        ],
    )

    price = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product} x {self.quantity} (Order #{self.order_id})"
