from django.views import View
from django.views.generic import TemplateView
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from shop.models import ProductModel, ProductStatusType
from .cart import CartSession

@method_decorator(csrf_exempt, name="dispatch")
class SessionAddProductView(View):
    def post(self, request):
        product_id = request.POST.get("product_id")
        if not product_id or not ProductModel.objects.filter(id=product_id, status=ProductStatusType.publish.value).exists():
            return JsonResponse({"error": "Product not found"}, status=404)
        cart = CartSession(request.session)
        cart.add_product(product_id)
        if request.user.is_authenticated:
            cart.merge_session_cart_in_db(request.user)
        return JsonResponse({"total_quantity": cart.get_total_quantity()})

@method_decorator(csrf_exempt, name="dispatch")
class SessionRemoveProductView(View):
    def post(self, request):
        product_id = request.POST.get("product_id")
        if not product_id:
            return JsonResponse({"error": "Invalid product"}, status=400)
        cart = CartSession(request.session)
        cart.remove_product(product_id)
        if request.user.is_authenticated:
            cart.merge_session_cart_in_db(request.user)
        return JsonResponse({"total_quantity": cart.get_total_quantity()})

@method_decorator(csrf_exempt, name="dispatch")
class SessionUpdateProductQuantityView(View):
    def post(self, request):
        product_id = request.POST.get("product_id")
        quantity = request.POST.get("quantity")
        if not product_id or not quantity:
            return JsonResponse({"error": "Invalid data"}, status=400)
        cart = CartSession(request.session)
        cart.update_product_quantity(product_id, quantity)
        if request.user.is_authenticated:
            cart.merge_session_cart_in_db(request.user)
        return JsonResponse({"total_quantity": cart.get_total_quantity()})

class CartSummaryView(TemplateView):
    template_name = "cart/cart-summary.html"
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cart = CartSession(self.request.session)
        cart_items = cart.get_cart_items()
        context["cart_items"] = cart_items
        context["total_quantity"] = cart.get_total_quantity()
        context["total_payment_price"] = cart.get_total_payment_amount()
        return context
