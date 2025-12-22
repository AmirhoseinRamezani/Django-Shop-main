from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from accounts.models import UserType
    
class DashboardHomeView(LoginRequiredMixin, View):

    def dispatch(self, request, *args, **kwargs):
        user = request.user

        if user.type == UserType.customer.value:
            return redirect("dashboard:customer:home")

        if user.type == UserType.admin.value:
            return redirect("dashboard:admin:home")

        return redirect("accounts:login")