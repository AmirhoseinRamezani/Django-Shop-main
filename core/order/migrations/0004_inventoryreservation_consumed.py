from django.db import migrations, models
from django.db.models import Q


def backfill_canonical_consumption(apps, schema_editor):
    OrderEvent = apps.get_model("order", "OrderEvent")
    Reservation = apps.get_model("order", "InventoryReservation")
    Payment = apps.get_model("payment", "PaymentModel")
    PaymentAttempt = apps.get_model("payment", "PaymentAttempt")
    db = schema_editor.connection.alias

    paid_events = (
        OrderEvent.objects.using(db)
        .filter(type="PAID")
        .only("order_id", "payload", "created_date")
        .iterator()
    )

    for event in paid_events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        payment_id = payload.get("payment_id")
        attempt_id = payload.get("attempt_id")

        if type(payment_id) is not int or type(attempt_id) is not int:
            continue

        payment_exists = Payment.objects.using(db).filter(
            pk=payment_id,
            order_id=event.order_id,
            status=2,
            is_consumed=True,
        ).exists()
        if not payment_exists:
            continue

        attempt_exists = PaymentAttempt.objects.using(db).filter(
            pk=attempt_id,
            payment_id=payment_id,
            status="success",
        ).exists()
        if not attempt_exists:
            continue

        Reservation.objects.using(db).filter(
            order_item__order_id=event.order_id,
            status="RESERVED",
        ).update(
            status="CONSUMED",
            consumed_at=event.created_date,
        )


def reverse_consumption_backfill(apps, schema_editor):
    Reservation = apps.get_model("order", "InventoryReservation")
    db = schema_editor.connection.alias
    Reservation.objects.using(db).filter(
        status="CONSUMED",
    ).update(
        status="RESERVED",
        consumed_at=None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("order", "0003_coupon_reservations"),
    ]

    operations = [
        migrations.AddField(
            model_name="inventoryreservation",
            name="consumed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="inventoryreservation",
            name="status",
            field=models.CharField(
                choices=[
                    ("RESERVED", "Reserved"),
                    ("RELEASED", "Released"),
                    ("CONSUMED", "Consumed"),
                ],
                db_index=True,
                default="RESERVED",
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="inventoryreservation",
            name="inventory_reservation_status_consistent",
        ),
        migrations.RunPython(
            backfill_canonical_consumption,
            reverse_consumption_backfill,
        ),
        migrations.AddConstraint(
            model_name="inventoryreservation",
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        status="RESERVED",
                        released_at__isnull=True,
                        consumed_at__isnull=True,
                    )
                    | Q(
                        status="RELEASED",
                        released_at__isnull=False,
                        consumed_at__isnull=True,
                    )
                    | Q(
                        status="CONSUMED",
                        released_at__isnull=True,
                        consumed_at__isnull=False,
                    )
                ),
                name="inventory_reservation_status_consistent",
            ),
        ),
    ]