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
        if not product_id:
            return JsonResponse({"error": "Invalid product"}, status=400)

        if not ProductModel.objects.filter(
            id=product_id,
            status=ProductStatusType.publish.value
        ).exists():
            return JsonResponse({"error": "Product not found"}, status=404)

        cart = CartSession(request.session)
        cart.add_product(product_id)

        if request.user.is_authenticated:
            cart.merge_session_cart_in_db(request.user)

        return JsonResponse({
            "total_quantity": cart.get_total_quantity()
        })
