from django.views.generic import View, TemplateView,UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from dashboard.permissions import HasAdminAccessPermission
from django.contrib.auth import views as auth_views
from dashboard.admin.forms import *
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from accounts.models import Profile
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _


class AdminSecurityEditView( HasAdminAccessPermission, LoginRequiredMixin, SuccessMessageMixin, auth_views.PasswordChangeView):
    template_name = "dashboard/admin/profile/security-edit.html"
    form_class = AdminPasswordChangeForm
    success_url = reverse_lazy("dashboard:admin:security-edit")
    success_message = _("Password updated successfully")


class AdminProfileEditView( HasAdminAccessPermission, LoginRequiredMixin, SuccessMessageMixin,UpdateView):
    template_name = "dashboard/admin/profile/profile-edit.html"
    form_class = AdminProfileEditForm
    success_url = reverse_lazy("dashboard:admin:profile-edit")
    success_message = _("Profile update successful")
    
    def get_object(self, queryset=None):
        return Profile.objects.get(user=self.request.user)

class AdminProfileImageEditView( HasAdminAccessPermission, LoginRequiredMixin, SuccessMessageMixin,UpdateView):
    http_method_names=["post"]
    model = Profile
    fields= [
        "image"
    ]
    success_url = reverse_lazy("dashboard:admin:profile-edit")
    success_message = _("Profile image update successful")
    
    def get_object(self, queryset=None):
        return Profile.objects.get(user=self.request.user)
    
    def form_invalid(self, form):
        messages.error(self.request,_("There was a problem sending the image, please check and try again"))
        return redirect(self.success_url)