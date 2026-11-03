from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from events.dispatchers import dispatch
from events.models.outbox import OutboxEvent, OutboxStatus


@dataclass(frozen=True, slots=True)
class ProcessOutboxResult:
    claimed: int = 0
    processed: int = 0
    retried: int = 0
    failed: int = 0
    lost_claims: int = 0


def process_outbox(
    batch_size: int = 50,
    max_retry: int = 5,
    *,
    lease_seconds: int = 300,
    retry_base_seconds: int = 5,
    retry_max_seconds: int = 900,
) -> ProcessOutboxResult:
    """Claim a bounded batch, dispatch outside DB locks, then acknowledge.

    This is an at-least-once delivery mechanism, not exactly-once delivery.
    Handler implementations must be idempotent using ``event.event_id``.
    """

    _validate_options(
        batch_size=batch_size,
        max_retry=max_retry,
        lease_seconds=lease_seconds,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )

    claimed_events = _claim_batch(
        batch_size=batch_size,
        max_retry=max_retry,
        lease_seconds=lease_seconds,
    )

    processed = retried = failed = lost_claims = 0

    for event in claimed_events:
        token = event.claim_token
        try:
            # No transaction or row lock is held while handlers perform I/O.
            dispatch(event)
        except Exception as exc:
            outcome = _record_failure(
                event_id=event.pk,
                claim_token=token,
                retry_count=event.retry_count + 1,
                max_retry=max_retry,
                error=exc,
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )
            if outcome == OutboxStatus.failed:
                failed += 1
            elif outcome == OutboxStatus.pending:
                retried += 1
            else:
                lost_claims += 1
        else:
            updated = OutboxEvent.objects.filter(
                pk=event.pk,
                status=OutboxStatus.processing,
                claim_token=token,
            ).update(
                status=OutboxStatus.processed,
                processed_date=timezone.now(),
                last_error="",
                claimed_at=None,
                claim_token=None,
            )
            if updated:
                processed += 1
            else:
                # A newer lease owns the event. A stale worker must not ack it.
                lost_claims += 1

    return ProcessOutboxResult(
        claimed=len(claimed_events),
        processed=processed,
        retried=retried,
        failed=failed,
        lost_claims=lost_claims,
    )


def _claim_batch(*, batch_size: int, max_retry: int, lease_seconds: int):
    now = timezone.now()
    lease_expired_before = now - timedelta(seconds=lease_seconds)

    with transaction.atomic():
        # Do not leave legacy/exhausted pending rows permanently unclaimable.
        OutboxEvent.objects.filter(
            Q(
                status=OutboxStatus.pending,
                retry_count__gte=max_retry,
            )
            | Q(
                status=OutboxStatus.processing,
                retry_count__gte=max_retry,
                claimed_at__lte=lease_expired_before,
            )
        ).update(
            status=OutboxStatus.failed,
            last_error="Retry limit reached before claim.",
            claimed_at=None,
            claim_token=None,
        )

        queryset = OutboxEvent.objects.filter(
            Q(
                status=OutboxStatus.pending,
                available_at__lte=now,
                retry_count__lt=max_retry,
            )
            | Q(
                status=OutboxStatus.processing,
                claimed_at__lte=lease_expired_before,
                retry_count__lt=max_retry,
            )
        ).order_by("created_date", "pk")

        # PostgreSQL uses SKIP LOCKED for competing workers. The fallback keeps
        # development/test databases functional but is not a concurrency guarantee.
        queryset = queryset.select_for_update(
            skip_locked=connection.features.has_select_for_update_skip_locked,
        )

        events = list(queryset[:batch_size])
        for event in events:
            event.status = OutboxStatus.processing
            event.claimed_at = now
            event.claim_token = uuid.uuid4()
            event.save(
                update_fields=("status", "claimed_at", "claim_token"),
            )

    return events


def _record_failure(
    *,
    event_id: int,
    claim_token: uuid.UUID,
    retry_count: int,
    max_retry: int,
    error: Exception,
    retry_base_seconds: int,
    retry_max_seconds: int,
):
    now = timezone.now()
    is_terminal = retry_count >= max_retry
    status = OutboxStatus.failed if is_terminal else OutboxStatus.pending
    delay = min(
        retry_base_seconds * (2 ** max(retry_count - 1, 0)),
        retry_max_seconds,
    )
    message = f"{type(error).__name__}: {error}"[:2000]

    updated = OutboxEvent.objects.filter(
        pk=event_id,
        status=OutboxStatus.processing,
        claim_token=claim_token,
    ).update(
        status=status,
        retry_count=retry_count,
        last_error=message,
        available_at=now + timedelta(seconds=delay),
        claimed_at=None,
        claim_token=None,
    )
    return status if updated else None


def _validate_options(
    *,
    batch_size: int,
    max_retry: int,
    lease_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    values = {
        "batch_size": batch_size,
        "max_retry": max_retry,
        "lease_seconds": lease_seconds,
        "retry_base_seconds": retry_base_seconds,
        "retry_max_seconds": retry_max_seconds,
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer.")
    if retry_base_seconds > retry_max_seconds:
        raise ValueError("retry_base_seconds cannot exceed retry_max_seconds.")
    if lease_seconds > 86400:
        raise ValueError("lease_seconds cannot exceed 86400.")
    if retry_max_seconds > 31536000:
        raise ValueError("retry_max_seconds cannot exceed one year.")
    if batch_size > 1000:
        raise ValueError("batch_size cannot exceed 1000.")
    if max_retry > 32767:
        raise ValueError("max_retry exceeds PostgreSQL PositiveSmallIntegerField capacity.")