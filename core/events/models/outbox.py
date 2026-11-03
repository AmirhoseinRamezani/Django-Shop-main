# events/models/outbox.py
from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class OutboxStatus(models.TextChoices):
    pending = "pending", "Pending"
    processing = "processing", "Processing"
    processed = "processed", "Processed"
    failed = "failed", "Failed"


class OutboxEvent(models.Model):
    """Durable message in the transactional outbox.

    Delivery is at-least-once. Consumers must use ``event_id`` as their
    idempotency key because a worker can die after an external side effect
    succeeds but before the database records the acknowledgement.
    """

    event_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="Globally unique idempotency key for this event.",
    )
    topic = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Stable routing key, for example: order.paid.",
    )
    payload = models.JSONField(
        help_text="Versioned, JSON-serializable event payload.",
    )
    status = models.CharField(
        max_length=20,
        choices=OutboxStatus.choices,
        default=OutboxStatus.pending,
        db_index=True,
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, null=True)

    created_date = models.DateTimeField(auto_now_add=True)
    processed_date = models.DateTimeField(null=True, blank=True)

    # Lease metadata fences off stale workers and makes crashed claims recoverable.
    available_at = models.DateTimeField(
        default=timezone.now,
        help_text="Earliest time at which this event may be claimed.",
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ("created_date", "pk")
        indexes = [
            models.Index(fields=("status", "retry_count"), name="events_outb_status_e17a58_idx"),
            models.Index(fields=("status", "created_date"), name="events_outb_status_01c531_idx"),
            models.Index(fields=("topic", "status"), name="events_outb_topic_134189_idx"),
            models.Index(fields=("status", "available_at"), name="events_outb_status_avail_idx"),
            models.Index(fields=("status", "claimed_at"), name="events_outb_status_claim_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        status=OutboxStatus.processing,
                        claim_token__isnull=False,
                        claimed_at__isnull=False,
                    )
                    | (
                        ~Q(status=OutboxStatus.processing)
                        & Q(claim_token__isnull=True, claimed_at__isnull=True)
                    )
                ),
                name="outbox_claim_metadata_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_id} {self.topic} [{self.status}]"