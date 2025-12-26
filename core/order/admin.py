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
    readonly_fields = ("product", "quantity", "price")


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

    def final_price(self, obj):
        return obj.get_price()
    final_price.short_description = "مبلغ نهایی"

    def has_coupon(self, obj):
        return bool(obj.coupon_code)
    has_coupon.boolean = True
    has_coupon.short_description = "کوپن؟"

@admin.register(CouponModel)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "discount_percent",
        "used_count",
        "max_limit_usage",
        "is_active",
        "expiration_date",
    )
    list_filter = ("is_active",)
    search_fields = ("code",)


@admin.register(UserAddressModel)
class UserAddressAdmin(admin.ModelAdmin):
    list_display = ("user", "city", "state", "zip_code")
    search_fields = ("user__username", "city")
