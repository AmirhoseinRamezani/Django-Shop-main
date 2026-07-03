# order/policies.py
from django.core.exceptions import PermissionDenied, ValidationError
from django.conf import settings
from django.utils import timezone

from shop.constants import SiteSaleType
from order.models import OrderStatusType
from django.utils.translation import gettext_lazy as _
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
        if settings.SITE_SALE_TYPE != SiteSaleType.ONLINE:
            raise PermissionDenied(_("Online sales are disabled"))

        return True

    @staticmethod
    def can_view(user, order):
        """
        User can view order only if:
        - staff
        - or owner of the order
        """
        if not user or not user.is_authenticated:
            raise PermissionDenied(_("Authentication required"))

        if user.is_staff or order.user_id == user.id:
            return True

        raise PermissionDenied(_("Access denied"))

    @staticmethod
    def can_refund(user, order):
        """
        Only staff can refund paid orders.
        """
        if not user.is_staff:
            raise PermissionDenied(_("Admin access required"))

        if not order.is_paid:
            raise PermissionDenied(_("Only paid orders can be refunded"))

        return True
    
    @staticmethod
    def can_pay(order):
        if order.status != OrderStatusType.pending:
            raise ValidationError(_("This order is not payable"))

        if order.is_expired():
            raise ValidationError(_("The payment deadline for this order has passed"))

        return True

    @staticmethod
    def can_expire(order):
        if order.status != OrderStatusType.pending:
            return False

        if order.expire_at and order.expire_at <= timezone.now():
            return True

        return False

    @staticmethod
    def can_retry_payment(order):
        
        return (
            not order.is_expired()
            and order.status in {
                OrderStatusType.pending,
                OrderStatusType.failed,
            }
        )