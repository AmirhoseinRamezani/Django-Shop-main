# shop/selectors.py
from .models import ProductModel, WishlistProductModel
from .constants import ProductStatusType


def get_published_products():
    return ProductModel.objects.filter(
        status=ProductStatusType.PUBLISH
    )


def get_user_wishlist_ids(user):
    if not user.is_authenticated:
        return []
    return WishlistProductModel.objects.filter(
        user=user
    ).values_list("product_id", flat=True)
