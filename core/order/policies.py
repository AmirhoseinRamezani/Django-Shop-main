from django.core.exceptions import PermissionDenied
from django.conf import settings


class OrderPolicy:

    @staticmethod
    def can_create_order(user):
        if not user.is_authenticated:
            raise PermissionDenied("Login required")

        if settings.SITE_SALE_TYPE != "ONLINE":
            raise PermissionDenied("Online sales disabled")
