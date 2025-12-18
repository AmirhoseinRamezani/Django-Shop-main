from .models import WishlistProductModel


def toggle_wishlist(user, product_id) -> str:
    obj, created = WishlistProductModel.objects.get_or_create(
        user=user,
        product_id=product_id
    )
    if not created:
        obj.delete()
        return "محصول از لیست علایق حذف شد"
    return "محصول به لیست علایق اضافه شد"
