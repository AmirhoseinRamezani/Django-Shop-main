# events/services/processor.py

from django.utils import timezone
from django.db import transaction

from events.models.outbox import OutboxEvent, OutboxStatus
from events.services.dispatchers import dispatch

@transaction.atomic
def process_outbox(batch_size: int =50, max_retry: int =5):
    """
    Consume pending Outbox events safely.
    Supports concurrent workers via SELECT FOR UPDATE SKIP LOCKED.
    """
    
    events = (
        OutboxEvent.objects
        .select_for_update(skip_locked=True)
        .filter(status=OutboxStatus.pending, retry_count__lt=max_retry)[:batch_size]
        .order_by("created_date")[:batch_size]
    )

    for event in events:
        try:
            dispatch(event)
            event.status = OutboxStatus.processed
            event.processed_date = timezone.now()

        except Exception as e:
            event.retry_count += 1
            event.last_error = str(e)[:2000]
            
            if event.retry_count >= max_retry:
                event.status = OutboxStatus.failed

        event.save(update_fields=[
            "status",
            "retry_count",
            "last_error",
            "processed_date",
        ])
