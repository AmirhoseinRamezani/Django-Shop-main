from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("order", "0006_alter_orderevent_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ordermodel",
            name="coupon",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="orders",
                to="order.couponmodel",
            ),
        ),
    ]