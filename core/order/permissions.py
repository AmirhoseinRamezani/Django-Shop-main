from django.contrib.auth.mixins import UserPassesTestMixin
from accounts.models import UserType


class IsCustomer(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and \
               self.request.user.type == UserType.customer


class IsSeller(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and \
               self.request.user.type == UserType.seller
