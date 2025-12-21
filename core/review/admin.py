from django.contrib import admin
from .models import ReviewModel


@admin.register(ReviewModel)
class ReviewModelAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "product", "rate", "status", "created_date")
    list_filter = ("status", "rate", "created_date")
    search_fields = ("user__phone", "product__title")
    ordering = ("-created_date",)
