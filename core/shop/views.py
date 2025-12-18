from django.views.generic import ListView, DetailView, View
from django.http import JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import ProductModel, ProductCategoryModel
from .selectors import get_published_products, get_user_wishlist_ids
from .services import toggle_wishlist

from review.models import ReviewModel, ReviewStatusType


class ShopProductGridView(ListView):
    template_name = "shop/product-grid.html"
    paginate_by = 9

    def get_queryset(self):
        qs = get_published_products()

        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(title__icontains=q)

        category_id = self.request.GET.get("category_id")
        if category_id:
            qs = qs.filter(category__id=category_id)

        min_price = self.request.GET.get("min_price")
        if min_price:
            qs = qs.filter(price__gte=min_price)

        max_price = self.request.GET.get("max_price")
        if max_price:
            qs = qs.filter(price__lte=max_price)

        order_by = self.request.GET.get("order_by")
        if order_by:
            qs = qs.order_by(order_by)

        return qs.distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = ProductCategoryModel.objects.all()
        ctx["wishlist_items"] = get_user_wishlist_ids(self.request.user)
        ctx["total_items"] = self.get_queryset().count()
        return ctx


class ShopProductDetailView(DetailView):
    template_name = "shop/product-detail.html"
    queryset = get_published_products()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        product = self.object

        reviews = ReviewModel.objects.filter(
            product=product,
            status=ReviewStatusType.accepted
        )

        ctx["reviews"] = reviews
        ctx["wishlist_items"] = get_user_wishlist_ids(self.request.user)

        total = reviews.count()
        ctx["reviews_count"] = {
            f"rate_{i}": reviews.filter(rate=i).count()
            for i in range(1, 6)
        }
        ctx["reviews_avg"] = {
            f"rate_{i}": round((ctx["reviews_count"][f"rate_{i}"] / total) * 100, 2)
            if total else 0
            for i in range(1, 6)
        }
        return ctx


class AddOrRemoveWishlistView(LoginRequiredMixin, View):
    def post(self, request):
        product_id = request.POST.get("product_id")
        message = toggle_wishlist(request.user, product_id)
        return JsonResponse({"message": message})
