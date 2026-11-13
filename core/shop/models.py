# shop/models.py
from django.db import models
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from .constants import ProductStatusType
from django.utils.translation import gettext_lazy as _


class ProductCategoryModel(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, allow_unicode=True)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_date",)

    def __str__(self):
        return self.title


class ProductModel(models.Model):
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="products"
    )
    category = models.ManyToManyField(
        ProductCategoryModel,
        related_name="products"
    )

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, allow_unicode=True)

    image = models.ImageField(
        upload_to="product/main/",
        default="default/product-image.png"
    )

    description = models.TextField()
    brief_description = models.TextField(blank=True)

    stock = models.PositiveIntegerField(default=0)

    status = models.IntegerField(
        choices=ProductStatusType.choices,
        default=ProductStatusType.DRAFT
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        validators=[MinValueValidator(0)]
    )

    discount_percent = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    avg_rate = models.FloatField(default=0)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    
    # Product Identity
    # -----------------------------------------

    sku = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_("Unique stock keeping unit."),
    )

    barcode = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Optional unique product barcode."),
    )

    # -----------------------------------------
    # Inventory
    # -----------------------------------------

    reserved_stock = models.PositiveIntegerField(
        default=0,
        help_text=_(
            "Quantity reserved by active orders "
            "and not yet finalized."
        ),
    )

    class Meta:
        ordering = ("-created_date",)
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["sku"]),
            models.Index(fields=["barcode"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(stock__gte=0)
                ),
                name="product_stock_non_negative",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(
                        reserved_stock__gte=0
                    )
                ),
                name="product_reserved_stock_non_negative",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(
                        reserved_stock__lte=models.F(
                            "stock"
                        )
                    )
                ),
                name="product_reserved_stock_lte_stock",
            ),
        ]

    def __str__(self):
        return self.title

    @property
    def available_stock(self):
        return max(
            self.stock
            - self.reserved_stock,
            0,
        )
        
    @property
    def final_price(self) -> int:
        if not self.discount_percent:
            return int(self.price)
        discount = (self.price * Decimal(self.discount_percent)) / 100
        return int(self.price - discount)

    @property
    def is_discounted(self) -> bool:
        return self.discount_percent > 0

    @property
    def is_available(self) -> bool:
        return self.status == ProductStatusType.PUBLISH and self.stock > 0


class InventoryAdjustmentDirection(models.TextChoices):
    INCREASE = "INCREASE", _("Increase")
    DECREASE = "DECREASE", _("Decrease")


class InventoryAdjustmentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(_("Inventory adjustment records are immutable."))

    def delete(self):
        raise ValidationError(_("Inventory adjustment records cannot be deleted."))

    def bulk_create(self, *args, **kwargs):
        raise ValidationError(
            _("Inventory adjustments must be created through InventoryAdjustmentService.")
        )

    def bulk_update(self, *args, **kwargs):
        raise ValidationError(_("Inventory adjustment records are immutable."))


class InventoryAdjustmentManager(models.Manager.from_queryset(InventoryAdjustmentQuerySet)):
    pass


class InventoryAdjustment(models.Model):
    """Immutable audit record for an authorized manual stock adjustment."""

    product = models.ForeignKey(
        ProductModel,
        on_delete=models.PROTECT,
        related_name="inventory_adjustments",
    )
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="inventory_adjustments",
    )
    direction = models.CharField(
        max_length=8,
        choices=InventoryAdjustmentDirection.choices,
    )
    quantity = models.PositiveIntegerField()
    previous_stock = models.PositiveIntegerField()
    resulting_stock = models.PositiveIntegerField()
    reason = models.TextField()
    idempotency_key = models.CharField(max_length=128, unique=True)
    request_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = InventoryAdjustmentManager()

    class Meta:
        ordering = ("-created_at", "-pk")
        base_manager_name = "objects"
        default_manager_name = "objects"
        permissions = [
            (
                "adjust_product_stock",
                "Can manually adjust product stock",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="inventory_adjustment_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(previous_stock__gte=0),
                name="inventory_adjustment_previous_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(resulting_stock__gte=0),
                name="inventory_adjustment_result_nonnegative",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="inventory_adjustment_reason_nonempty",
            ),
            models.CheckConstraint(
                condition=~models.Q(idempotency_key=""),
                name="inventory_adjustment_key_nonempty",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    direction__in=(
                        InventoryAdjustmentDirection.INCREASE,
                        InventoryAdjustmentDirection.DECREASE,
                    )
                ),
                name="inventory_adjustment_direction_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    request_fingerprint__regex=r"^[0-9a-f]{64}$"
                ),
                name="inventory_adjustment_fingerprint_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        direction=InventoryAdjustmentDirection.INCREASE,
                        resulting_stock=models.F("previous_stock")
                        + models.F("quantity"),
                    )
                    | models.Q(
                        direction=InventoryAdjustmentDirection.DECREASE,
                        previous_stock__gte=models.F("quantity"),
                        resulting_stock=models.F("previous_stock")
                        - models.F("quantity"),
                    )
                ),
                name="inventory_adjustment_stock_math_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(_("Inventory adjustment records are immutable."))
        if not getattr(self, "_service_write", False):
            raise ValidationError(
                _("Inventory adjustments must be created through InventoryAdjustmentService.")
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Inventory adjustment records cannot be deleted."))

    def __str__(self):
        return (
            f"{self.get_direction_display()} {self.quantity} "
            f"for {self.product_id} ({self.idempotency_key})"
        )


class ProductImageModel(models.Model):
    product = models.ForeignKey(
        ProductModel,
        on_delete=models.CASCADE,
        related_name="images"
    )
    file = models.ImageField(upload_to="product/extra/")

    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_date",)


class WishlistProductModel(models.Model):
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="wishlist_items"
    )
    product = models.ForeignKey(
        ProductModel,
        on_delete=models.CASCADE,
        related_name="wishlisted_by"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "product"),
                name="unique_user_product_wishlist"
            )
        ]

    def __str__(self):
        return f"{self.user_id} → {self.product_id}"
