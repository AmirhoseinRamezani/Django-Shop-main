#order/events/order_event.py
from django.db import models
from django.conf import settings


class OrderEventType(models.TextChoices):
    CREATED = "CREATED", "Order Created"
    PAYMENT_STARTED = "PAYMENT_STARTED", "Payment Started"
    PAID = "PAID", "Payment Successful"
    EXPIRED = "EXPIRED", "Order Expired"
    CANCELLED = "CANCELLED", "Order Cancelled"
    REFUNDED = "REFUNDED", "Order Refunded"
    ADMIN_NOTE = "ADMIN_NOTE", "Admin Note"


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
