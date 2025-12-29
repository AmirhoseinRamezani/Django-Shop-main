# order/views/order.py

from rest_framework.viewsets import ReadOnlyModelViewSet
from order.models import OrderModel
from order.serializers import OrderSerializer


class OrderViewSet(ReadOnlyModelViewSet):
    serializer_class = OrderSerializer

    def get_queryset(self):
        qs = OrderModel.objects.all()

        # 🔒 حفظ حریم خصوصی
        if not self.request.user.is_staff:
            qs = qs.filter(user=self.request.user)

        return qs
