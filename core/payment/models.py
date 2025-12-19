from django.db import models


class PaymentStatusType(models.IntegerChoices):
    pending = 1, "در انتظار"
    success = 2, "موفق"
    failed = 3, "ناموفق"


class PaymentModel(models.Model):
    authority_id = models.CharField(max_length=255)
    ref_id = models.CharField(max_length=255, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    status = models.IntegerField(
        choices=PaymentStatusType.choices,
        default=PaymentStatusType.pending
    )
    response_json = models.JSONField(default=dict)

    created_date = models.DateTimeField(auto_now_add=True)
