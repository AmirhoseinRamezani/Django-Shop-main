from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("payment", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="paymentattempt",
            constraint=models.UniqueConstraint(
                condition=Q(status="pending"),
                fields=("payment",),
                name="payment_one_pending_attempt_per_payment",
            ),
        ),
    ]
