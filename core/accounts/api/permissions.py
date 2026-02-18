# accounts/api/permissons.py
from rest_framework.permissions import BasePermission

class IsAPIAuthenticated(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
        )
