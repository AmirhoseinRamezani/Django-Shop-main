from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("payment", "0005_order_payment_financial_snapshot_guards"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="paymentmodel",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AlterModelOptions(
            name="paymentattempt",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AlterModelOptions(
            name="refund",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
    ]