from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("payment", "0002_payment_one_pending_attempt"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentattempt",
            name="retry_idempotency_key",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Stable idempotency key for the retry request "
                    "that created this attempt."
                ),
                max_length=128,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="paymentattempt",
            constraint=models.CheckConstraint(
                condition=(
                    Q(retry_idempotency_key__isnull=True)
                    | Q(retry_idempotency_key__gt="")
                ),
                name="payment_attempt_retry_key_valid",
            ),
        ),
    ]
