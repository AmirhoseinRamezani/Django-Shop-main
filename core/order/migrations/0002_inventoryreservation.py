from django.db import migrations, models
from django.db.models import Q
from django.core.validators import MinValueValidator


def backfill_reservations(apps, schema_editor):
    OrderItem = apps.get_model("order", "OrderItemModel")
    Reservation = apps.get_model("order", "InventoryReservation")
    Order = apps.get_model("order", "OrderModel")

    cancelled_status = 10
    db_alias = schema_editor.connection.alias

    items = (
        OrderItem.objects.using(db_alias)
        .select_related("order")
        .exclude(order__status=cancelled_status)
        .iterator()
    )

    Reservation.objects.using(db_alias).bulk_create(
        [
            Reservation(
                order_item_id=item.pk,
                quantity=item.quantity,
                status="RESERVED",
            )
            for item in items
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("order", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="InventoryReservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "quantity",
                    models.PositiveIntegerField(
                        validators=[MinValueValidator(1)],
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("RESERVED", "Reserved"),
                            ("RELEASED", "Released"),
                        ],
                        db_index=True,
                        default="RESERVED",
                        max_length=20,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "released_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "order_item",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        related_name="inventory_reservation",
                        to="order.orderitemmodel",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=Q(quantity__gte=1),
                        name="inventory_reservation_quantity_positive",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(
                                status="RESERVED",
                                released_at__isnull=True,
                            )
                            | Q(
                                status="RELEASED",
                                released_at__isnull=False,
                            )
                        ),
                        name="inventory_reservation_status_consistent",
                    ),
                ],
            },
        ),
        migrations.RunPython(
            backfill_reservations,
            migrations.RunPython.noop,
        ),
    ]
