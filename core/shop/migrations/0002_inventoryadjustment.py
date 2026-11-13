# Generated for controlled, auditable manual inventory adjustments.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InventoryAdjustment",
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
                ("direction", models.CharField(
                    choices=[("INCREASE", "Increase"), ("DECREASE", "Decrease")],
                    max_length=8,
                )),
                ("quantity", models.PositiveIntegerField()),
                ("previous_stock", models.PositiveIntegerField()),
                ("resulting_stock", models.PositiveIntegerField()),
                ("reason", models.TextField()),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("request_fingerprint", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory_adjustments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory_adjustments",
                        to="shop.productmodel",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-pk"),
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "permissions": [
                    ("adjust_product_stock", "Can manually adjust product stock"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="inventoryadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(("quantity__gt", 0)),
                name="inventory_adjustment_quantity_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventoryadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(("previous_stock__gte", 0)),
                name="inventory_adjustment_previous_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventoryadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(("resulting_stock__gte", 0)),
                name="inventory_adjustment_result_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventoryadjustment",
            constraint=models.CheckConstraint(
                condition=~models.Q(("reason", "")),
                name="inventory_adjustment_reason_nonempty",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventoryadjustment",
            constraint=models.CheckConstraint(
                condition=~models.Q(("idempotency_key", "")),
                name="inventory_adjustment_key_nonempty",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventoryadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(("direction__in", ("INCREASE", "DECREASE"))),
                name="inventory_adjustment_direction_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventoryadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(("request_fingerprint__regex", "^[0-9a-f]{64}$")),
                name="inventory_adjustment_fingerprint_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventoryadjustment",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        ("direction", "INCREASE"),
                        ("resulting_stock", models.F("previous_stock") + models.F("quantity")),
                    )
                    | models.Q(
                        ("direction", "DECREASE"),
                        ("previous_stock__gte", models.F("quantity")),
                        ("resulting_stock", models.F("previous_stock") - models.F("quantity")),
                    )
                ),
                name="inventory_adjustment_stock_math_valid",
            ),
        ),
    ]