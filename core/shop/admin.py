from django.contrib import admin
from .models import (
    ProductModel,
    ProductImageModel,
    ProductCategoryModel,
    WishlistProductModel,
    InventoryAdjustment,
)


@admin.register(ProductModel)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "price", "discount_percent",
        "stock", "reserved_stock", "status", "created_date"
    )
    readonly_fields = ("stock", "reserved_stock")
    actions = None
    list_filter = ("status", "created_date")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(ProductCategoryModel)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "created_date")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(ProductImageModel)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "created_date")


@admin.register(InventoryAdjustment)
class InventoryAdjustmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "direction",
        "quantity",
        "previous_stock",
        "resulting_stock",
        "actor",
        "created_at",
    )
    list_filter = ("direction", "created_at")
    search_fields = ("product__title", "actor__email", "idempotency_key", "reason")
    readonly_fields = tuple(field.name for field in InventoryAdjustment._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff


@admin.register(WishlistProductModel)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "product")
