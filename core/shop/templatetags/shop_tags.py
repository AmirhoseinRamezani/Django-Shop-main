from django import template
from shop.selectors import get_published_products, get_user_wishlist_ids

register = template.Library()


@register.inclusion_tag("includes/latest-products.html", takes_context=True)
def show_latest_products(context):
    request = context["request"]
    return {
        "latest_products": get_published_products()[:8],
        "wishlist_items": get_user_wishlist_ids(request.user),
        "request": request,
    }
