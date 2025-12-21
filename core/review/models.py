from django.db import models
from shop.models import ProductModel
from django.core.validators import MaxValueValidator, MinValueValidator
from django.dispatch import receiver
from django.db.models.signals import post_save, post_delete
from django.db.models import Avg


class ReviewStatusType(models.IntegerChoices):
    pending = 1, "در انتظار تایید"
    accepted = 2, "تایید شده"
    rejected = 3, "رد شده"


class ReviewModel(models.Model):
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name="reviews"
    )
    product = models.ForeignKey(
        ProductModel,
        on_delete=models.CASCADE,
        related_name="reviews"
    )
    description = models.TextField()
    rate = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    status = models.IntegerField(
        choices=ReviewStatusType.choices,
        default=ReviewStatusType.pending.value
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_date"]
        unique_together = ("user", "product")  # هر کاربر فقط یک نظر

    def __str__(self):
        return f"{self.user} - {self.product}"

    def get_status(self):
        return {
            "id": self.status,
            "title": ReviewStatusType(self.status).name,
            "label": ReviewStatusType(self.status).label,
        }


def update_product_avg_rate(product):
    avg = ReviewModel.objects.filter(
        product=product,
        status=ReviewStatusType.accepted
    ).aggregate(avg=Avg("rate"))["avg"]

    product.avg_rate = round(avg, 1) if avg else 0
    product.save(update_fields=["avg_rate"])


@receiver(post_save, sender=ReviewModel)
def review_post_save(sender, instance, **kwargs):
    update_product_avg_rate(instance.product)


@receiver(post_delete, sender=ReviewModel)
def review_post_delete(sender, instance, **kwargs):
    update_product_avg_rate(instance.product)
