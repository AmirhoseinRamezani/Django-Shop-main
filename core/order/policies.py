from django.core.exceptions import PermissionDenied
from django.conf import settings


class OrderPolicy:
    """
    Centralized order access rules.
    All views/services should delegate authorization here.
    """
    @staticmethod
    def can_create_order(user):
        # Require authentication
        if not user or not user.is_authenticated:
            raise PermissionDenied("Authentication required")

        # Check global sale mode
        if settings.SITE_SALE_TYPE != "ONLINE":
            raise PermissionDenied("Online sales are disabled")

        return True

    @staticmethod
    def can_view(user, order):
        """
        User can view order only if:
        - staff
        - or owner of the order
        """
        if not user or not user.is_authenticated:
            raise PermissionDenied("Authentication required")

        if user.is_staff or order.user_id == user.id:
            return True

        raise PermissionDenied("Access denied")

    @staticmethod
    def can_refund(user, order):
        """
        Only staff can refund paid orders.
        """
        if not user.is_staff:
            raise PermissionDenied("Admin access required")

        if not order.is_paid:
            raise PermissionDenied("Only paid orders can be refunded")

        return True