from django.db import migrations, models
from django.db.models import F, Q
import django.db.models.deletion


def backfill_coupon_reservations(apps, schema_editor):
    Coupon = apps.get_model("order", "CouponModel")
    Order = apps.get_model("order", "OrderModel")
    Reservation = apps.get_model("order", "CouponReservation")
    Reconciliation = apps.get_model("order", "CouponReservationReconciliation")
    db = schema_editor.connection.alias

    paid_statuses = {3, 4, 5, 6, 7, 8, 9}
    cancelled_status = 10
    for coupon in Coupon.objects.using(db).order_by("pk").iterator():
        reserved_count = 0
        orders = Order.objects.using(db).filter(coupon_id=coupon.pk).order_by("created_date", "pk")
        for order in orders.iterator():
            if order.status in paid_statuses:
                status = "CONSUMED"
                consumed_at = order.paid_date or order.created_date
                released_at = None
                operation = "NONE"
                reconciliation_status = "RESOLVED"
                reason = ""
            elif order.status == cancelled_status:
                status = "RELEASED"
                consumed_at = None
                released_at = order.cancelled_date or order.created_date
                operation = "NONE"
                reconciliation_status = "RESOLVED"
                reason = ""
            elif coupon.used_count + reserved_count < coupon.max_limit_usage:
                status = "RESERVED"
                consumed_at = None
                released_at = None
                reserved_count += 1
                operation = "NONE"
                reconciliation_status = "RESOLVED"
                reason = ""
            else:
                # Never migrate an unresolved legacy Order without a capacity
                # slot. Stop deployment so the operator can reconcile legacy
                # usage before the invariant is enabled.
                raise RuntimeError(
                    f"Coupon {coupon.pk} has more active legacy Orders than "
                    "remaining capacity; reconcile Orders before applying "
                    "coupon reservation migration."
                )

            reservation = Reservation.objects.using(db).create(
                order_id=order.pk,
                coupon_id=coupon.pk,
                status=status,
                consumed_at=consumed_at,
                released_at=released_at,
            )
            Reconciliation.objects.using(db).create(
                order_id=order.pk,
                coupon_id=coupon.pk,
                reservation_id=reservation.pk,
                expected_operation=operation,
                status=reconciliation_status,
                failure_reason=reason,
                resolved_at=(order.created_date if reconciliation_status == "RESOLVED" else None),
            )
        Coupon.objects.using(db).filter(pk=coupon.pk).update(reserved_count=reserved_count)


class Migration(migrations.Migration):
    dependencies = [
        ("order", "0002_inventoryreservation"),
        ("payment", "0004_paymentresolution"),
    ]

    operations = [
        migrations.AddField(
            model_name="couponmodel",
            name="reserved_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="CouponReservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("RESERVED", "Reserved"), ("CONSUMED", "Consumed"), ("RELEASED", "Released")], db_index=True, default="RESERVED", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("coupon", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reservations", to="order.couponmodel")),
                ("order", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="coupon_reservation", to="order.ordermodel")),
            ],
            options={
                "constraints": [models.CheckConstraint(condition=(Q(status="RESERVED", consumed_at__isnull=True, released_at__isnull=True) | Q(status="CONSUMED", consumed_at__isnull=False, released_at__isnull=True) | Q(status="RELEASED", consumed_at__isnull=True, released_at__isnull=False)), name="coupon_reservation_state_consistent")],
                "indexes": [models.Index(fields=["coupon", "status"], name="coupon_res_status_idx")],
            },
        ),
        migrations.CreateModel(
            name="CouponReservationReconciliation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("expected_operation", models.CharField(choices=[("NONE", "No pending operation"), ("CONSUME", "Consume reservation"), ("RELEASE", "Release reservation"), ("REVIEW", "Manual review required")], default="NONE", max_length=12)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("RETRY", "Retry required"), ("RESOLVED", "Resolved")], db_index=True, default="RESOLVED", max_length=12)),
                ("failure_reason", models.TextField(blank=True)),
                ("retry_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("attempt", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="coupon_reconciliations", to="payment.paymentattempt")),
                ("coupon", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reconciliations", to="order.couponmodel")),
                ("order", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="coupon_reconciliation", to="order.ordermodel")),
                ("payment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="coupon_reconciliations", to="payment.paymentmodel")),
                ("reservation", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reconciliation", to="order.couponreservation")),
            ],
            options={
                "indexes": [models.Index(fields=["status", "updated_at"], name="coupon_recon_status_idx")],
            },
        ),
        migrations.RunPython(backfill_coupon_reservations, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="couponmodel",
            constraint=models.CheckConstraint(condition=Q(reserved_count__gte=0), name="coupon_reserved_count_non_negative"),
        ),
        migrations.AddConstraint(
            model_name="couponmodel",
            constraint=models.CheckConstraint(condition=Q(used_count__lte=F("max_limit_usage") - F("reserved_count")), name="coupon_usage_plus_reserved_lte_max"),
        ),
    ]