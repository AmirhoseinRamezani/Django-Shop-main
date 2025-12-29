# order/views/order_list.py

from django.views.generic import ListView
from order.models import OrderModel

#__________Privacy Policy________________
class OrderListView(ListView):
    model = OrderModel

    def get_queryset(self):
        qs = super().get_queryset()

        if not self.request.user.is_staff:
            qs = qs.filter(user=self.request.user)

        return qs
