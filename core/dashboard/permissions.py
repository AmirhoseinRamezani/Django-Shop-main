from django.contrib.auth.mixins import LoginRequiredMixin,UserPassesTestMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from accounts.models import UserType


class HasCustomerAccessPermission(UserPassesTestMixin):
    """
    Ensures user is authenticated AND has admin access
    Single source of truth for admin permissions
    """

    login_url = reverse_lazy("accounts:login")
    
    def test_func(self):
        return (
            self.request.user.is_authenticated
            and self.request.user.type == UserType.admin.value
        )

    def handle_no_permission(self):
        """
        Redirect non-admin users to dashboard home
        """
        return redirect(reverse_lazy("dashboard:home"))
    

class HasAdminAccessPermission(LoginRequiredMixin, UserPassesTestMixin):

    def test_func(self):
        if self.request.user.is_authenticated:
            return self.request.user.type == UserType.ADMIN
        return False