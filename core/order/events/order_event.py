#order/events/order_event.py
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class OrderEventType(models.TextChoices):
    CREATED = "CREATED", "Order Created"

    PAYMENT_STARTED = (
        "PAYMENT_STARTED",
        _("Payment Started")
    )

    PAID = (
        "PAID",
        _("Payment Successful")
    )

    PROCESSING = (
        "PROCESSING",
        _("Order Processing")
    )

    SHIPPED = (
        "SHIPPED",
        _("Order Shipped")
    )

    DELIVERED = (
        "DELIVERED",
        _("Order Delivered")
    )

    RETURN_REQUESTED = (
        "RETURN_REQUESTED",
        _("Return Requested")
    )

    RETURNED = (
        "RETURNED",
        _("Returned")
    )

    EXPIRED = (
        "EXPIRED",
        _("Order Expired")
    )

    CANCELLED = (
        "CANCELLED",
        _("Order Cancelled")
    )

    REFUNDED = (
        "REFUNDED",
        _("Order Refunded")
    )

    ADMIN_NOTE = (
        "ADMIN_NOTE",
        _("Admin Note")
    )


class OrderEvent(models.Model):
    order = models.ForeignKey(
        "order.OrderModel",
        on_delete=models.CASCADE,
        related_name="events"
    )

    type = models.CharField(
        max_length=30,
        choices=OrderEventType.choices
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    payload = models.JSONField(default=dict, blank=True)

    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_date",)

    def __str__(self):
        return f"{self.order_id} | {self.type}"
    
    @property
    def title(self):
        return {
            OrderEventType.CREATED:
                _("Order Created"),
            OrderEventType.PAYMENT_STARTED:
                _("Payment Started"),
            OrderEventType.PAID:
                _("Payment Successful"),
            OrderEventType.PROCESSING:
                _("Order Processing"),
            OrderEventType.SHIPPED:
                _("Order Shipped"),
            OrderEventType.DELIVERED:
                _("Order Delivered"),
            OrderEventType.RETURN_REQUESTED:
                _("Return Requested"),
            OrderEventType.RETURNED:
                _("Returned"),
            OrderEventType.CANCELLED:
                _("Cancelled"),
            OrderEventType.EXPIRED:
                _("Expired"),
            OrderEventType.REFUNDED:
                _("Refunded"),
        }.get(
            self.type,
            _("Unknown Event")
        )