from django.contrib import admin
from .models import (
    OrderModel,
    OrderItemModel,
    CouponModel,
    UserAddressModel
)


class OrderItemInline(admin.TabularInline):
    model = OrderItemModel
    extra = 0


@admin.register(OrderModel)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "full_name",
        "phone",
        "total_price",
        "status",
        "sale_type",
        "created_date",
    )
    list_filter = ("status", "sale_type")
    search_fields = ("full_name", "phone", "email")
    readonly_fields = ("created_date",)
    inlines = (OrderItemInline,)


@admin.register(CouponModel)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "discount_percent",
        "max_limit_usage",
        "used_count",
        "expiration_date",
    )

    def used_count(self, obj):
        return obj.used_by.count()


@admin.register(UserAddressModel)
class UserAddressAdmin(admin.ModelAdmin):
    list_display = ("user", "city", "state", "zip_code")
