# order/views/order.py

from rest_framework.viewsets import ReadOnlyModelViewSet
from order.models import OrderModel
from order.serializers import OrderSerializer
from order.policies import OrderPolicy


class OrderViewSet(ReadOnlyModelViewSet):
    """
    Read-only API for orders.
    Privacy preserved by policy.
    """
    serializer_class = OrderSerializer

    def get_queryset(self):
        user = self.request.user
        qs = OrderModel.objects.all()

        # Apply access policy
        if not user.is_staff:
            qs = qs.filter(user=user)

        return qs

    def get_object(self):
        order = super().get_object()
        OrderPolicy.can_view(self.request.user, order)
        return order
