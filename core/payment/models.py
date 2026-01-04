from django.db import models
from django.db.models import JSONField
from django.utils import timezone

class PaymentStatusType(models.IntegerChoices):
    pending = 1, "در انتظار"
    success = 2, "پرداخت موفق"
    failed = 3, "پرداخت ناموفق"


class PaymentModel(models.Model):
    order = models.ForeignKey(
        "order.OrderModel",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )
    
    authority_id = models.CharField(
        max_length=255,      
        unique=True,
        help_text="Gateway authority / token"
    )
    
    ref_id = models.BigIntegerField(null=True, blank=True)

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=0
    )
    gateway = models.CharField(
        max_length=50,
        default="ZARINPAL"
    )
    
    response_json = JSONField(
        default=dict,
        help_text="Raw gateway response"
    )
    response_code = models.IntegerField(null=True, blank=True)

    status = models.IntegerField(
        choices=PaymentStatusType.choices,
        default=PaymentStatusType.pending
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    paid_date = models.DateTimeField(null=True, blank=True)
    is_consumed = models.BooleanField(
        default=False,
        help_text="Used to finalize order (idempotency guard)"
    )
    
    class Meta:
        ordering = ("-created_date",)
        indexes = [
            models.Index(fields=["authority_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["order", "status"]),
        ]
        
    # ---------- Domain methods ----------
    def mark_success(self, ref_id, response=None):
        """
        Mark payment as successful.
        """
        self.status = PaymentStatusType.success
        self.ref_id = ref_id
        self.paid_date = timezone.now()
        if response is not None:
            self.response_json = response

        self.save(update_fields=[
            "status",
            "ref_id",
            "paid_date",
            "response_json",
        ])

    def mark_failed(self, response=None):
        """
        Mark payment as failed.
        """
        self.status = PaymentStatusType.failed
        if response is not None:
            self.response_json = response

        self.save(update_fields=["status", "response_json"])

    def __str__(self):
        return f"Payment #{self.id} ({self.get_status_display()})"