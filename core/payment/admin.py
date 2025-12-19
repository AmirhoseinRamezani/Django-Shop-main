from django.contrib import admin
from .models import PaymentModel


@admin.register(PaymentModel)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "authority_id",
        "amount",
        "status",
        "response_code",
        "created_date"
    )

    list_filter = ("status",)
    readonly_fields = ("response_json", "created_date", "updated_date")
