from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PaymentResolutionReason(models.TextChoices):
    ORDER_CANCELLED = "ORDER_CANCELLED", _("Order cancelled")
    ORDER_EXPIRED = "ORDER_EXPIRED", _("Order expired")
    ORDER_DEADLINE_PASSED = "ORDER_DEADLINE_PASSED", _("Order deadline passed")
    ORDER_ALREADY_PAID = "ORDER_ALREADY_PAID", _("Order already paid")
    FINALIZATION_INCONSISTENCY = "FINALIZATION_INCONSISTENCY", _("Finalization inconsistency")


class PaymentResolutionStatus(models.TextChoices):
    OPEN = "OPEN", _("Open")
    RESOLVED = "RESOLVED", _("Resolved")


class PaymentResolution(models.Model):
    """Durable audit record for a successful Payment not consumed by its Order."""

    payment = models.OneToOneField(
        "payment.PaymentModel",
        on_delete=models.PROTECT,
        related_name="resolution",
    )
    attempt = models.ForeignKey(
        "payment.PaymentAttempt",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolutions",
    )
    reason = models.CharField(max_length=40, choices=PaymentResolutionReason.choices)
    status = models.CharField(
        max_length=12,
        choices=PaymentResolutionStatus.choices,
        default=PaymentResolutionStatus.OPEN,
    )
    order_status_at_detection = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_resolutions_resolved",
    )
    resolution_note = models.TextField(blank=True)

    class Meta:
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(fields=("status", "created_at"), name="payres_status_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(status=PaymentResolutionStatus.OPEN, resolved_at__isnull=True)
                    | models.Q(status=PaymentResolutionStatus.RESOLVED, resolved_at__isnull=False)
                ),
                name="payment_resolution_status_timestamp",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.attempt_id and self.payment_id and self.attempt.payment_id != self.payment_id:
            raise ValidationError({"attempt": _("Attempt must belong to the same Payment.")})

    def __str__(self) -> str:
        return f"PaymentResolution(payment_id={self.payment_id}, status={self.status})"