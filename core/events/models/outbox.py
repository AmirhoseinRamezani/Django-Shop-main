# events/models/outbox.py

from django.db import models

class OutboxStatus(models.TextChoices):
    pending = "pending", "Pending"
    processed = "processed", "Processed"
    failed = "failed", "Failed"


class OutboxEvent(models.Model):
    """
    Durable event storage (Outbox Pattern).
    Each event MUST be idempotent.
    """
    topic = models.CharField(max_length=100, db_index=True, help_text="Routing key for dispatchers (e.g. user.otp)")
    payload = models.JSONField(help_text="Event data payload (must be serializable & validated)")

    status = models.CharField(
        max_length=20,
        choices=OutboxStatus.choices,
        default=OutboxStatus.pending,
        db_index=True
    )

    retry_count = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, null=True)

    created_date = models.DateTimeField(auto_now_add=True)
    processed_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_date"]
        indexes = [
            models.Index(fields=["status", "retry_count"]),
        ]

    def __str__(self):
        return f"{self.topic} [{self.status}]"
