from django.contrib import admin
from .models import PaymentModel


@admin.register(PaymentModel)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "authority_id",
        "amount",
        "response_code",
        "status",
        "created_date",
    )

    list_filter = ("status",)

    readonly_fields = (
        "authority_id",
        "ref_id",
        "amount",
        "response_code",
        "response_json",
        "created_date",
        "updated_date",
    )
