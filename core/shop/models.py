# shop/models.py
from django.db import models
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
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
