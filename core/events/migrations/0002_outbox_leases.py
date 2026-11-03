# Generated for durable outbox claiming and recovery.
import django.utils.timezone
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="outboxevent",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("processed", "Processed"),
                    ("failed", "Failed"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="outboxevent",
            name="available_at",
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                help_text="Earliest time at which this event may be claimed.",
            ),
        ),
        migrations.AddField(
            model_name="outboxevent",
            name="claimed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="outboxevent",
            name="claim_token",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddIndex(
            model_name="outboxevent",
            index=models.Index(
                fields=["status", "available_at"],
                name="events_outb_status_avail_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="outboxevent",
            index=models.Index(
                fields=["status", "claimed_at"],
                name="events_outb_status_claim_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="outboxevent",
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        status="processing",
                        claim_token__isnull=False,
                        claimed_at__isnull=False,
                    )
                    | (
                        ~Q(status="processing")
                        & Q(claim_token__isnull=True, claimed_at__isnull=True)
                    )
                ),
                name="outbox_claim_metadata_consistent",
            ),
        ),
    ]