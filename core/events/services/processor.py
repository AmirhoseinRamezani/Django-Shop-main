# events/services/processor.py

from django.utils import timezone
from django.db import transaction

from events.models.outbox import OutboxEvent, OutboxStatus
from events.services.dispatchers import dispatch


@transaction.atomic
def process_outbox(batch_size: int = 50, max_retry: int = 5):
    """
    Safely process pending Outbox events.

    - Deterministic ordering
    - Concurrency-safe (SKIP LOCKED)
    - Atomic per-event dispatch
    - Retry & fail handling
    """

    events = (
        OutboxEvent.objects
        .select_for_update(skip_locked=True)
        .filter(
            status=OutboxStatus.pending,
            retry_count__lt=max_retry,
        )
        .order_by("created_date")[:batch_size]
    )

    for event in events:
        try:
            with transaction.atomic():
                dispatch(event)
                event.status = OutboxStatus.processed
                event.processed_date = timezone.now()
                event.retry_count = 0
                event.last_error = ""

        except Exception as exc:
            event.retry_count += 1
            event.last_error = str(exc)[:2000]

            if event.retry_count >= max_retry:
                event.status = OutboxStatus.failed

        event.save(update_fields=[
            "status",
            "retry_count",
            "last_error",
            "processed_date",
        ])
