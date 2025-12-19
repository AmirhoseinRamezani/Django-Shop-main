from django.contrib import admin
from .models import OrderModel, OrderItemModel

class OrderItemInline(admin.TabularInline):
    model = OrderItemModel
    extra = 0
    
@admin.register(OrderModel)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "full_name",
        "phone",
        "payable_amount",
        "status",
        "is_online",
        "created_date"
    )

    list_filter = ("status", "is_online")
    search_fields = ("full_name", "phone", "email")
    readonly_fields = ("created_date", "updated_date")

    fieldsets = (
        ("اطلاعات خریدار", {
            "fields": ("full_name", "phone", "email", "address")
        }),
        ("اطلاعات مالی", {
            "fields": ("total_price", "discount_amount", "payable_amount")
        }),
        ("وضعیت سفارش", {
            "fields": ("status", "is_online")
        }),
        ("تاریخ‌ها", {
            "fields": ("created_date", "updated_date")
        }),
    )
