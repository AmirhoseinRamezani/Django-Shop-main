# order/views/order.py
from django.views.generic import ListView
from rest_framework.viewsets import ReadOnlyModelViewSet

from order.models import OrderModel
from order.serializers import OrderSerializer

# --------------------
# Shared privacy logic
# --------------------
def filter_orders_for_user(qs, user):
    """
    Privacy filter:
    - staff: see all
    - customer: see own orders only
    """
    if user.is_staff:
        return qs
    return qs.filter(user=user)

# --------------------
# Django Template View
# --------------------
class OrderListView(ListView):
    model = OrderModel
    paginate_by = 10

    def get_queryset(self):
        qs = super().get_queryset()

        qs = filter_orders_for_user(qs, self.request.user)

        return qs
    
# --------------------
# API View (Read only)
# --------------------
class OrderViewSet(ReadOnlyModelViewSet):
    serializer_class = OrderSerializer

    def get_queryset(self):
        qs = OrderModel.objects.all()
        qs = filter_orders_for_user(qs, self.request.user)
        
        return qs
