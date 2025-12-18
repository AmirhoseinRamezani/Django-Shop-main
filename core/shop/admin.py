from django.contrib import admin
from .models import (
    ProductModel,
    ProductImageModel,
    ProductCategoryModel,
    WishlistProductModel
)


@admin.register(ProductModel)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "price", "discount_percent",
        "stock", "status", "created_date"
    )
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


@admin.register(WishlistProductModel)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "product")
