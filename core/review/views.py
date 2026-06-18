from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.edit import CreateView
from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.contrib import messages
from .forms import SubmitReviewForm
from .models import ReviewModel

from django.utils.translation import gettext_lazy as _

class SubmitReviewView(LoginRequiredMixin, CreateView):
    http_method_names = ["post"]
    model = ReviewModel
    form_class = SubmitReviewForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["initial"] = {"user": self.request.user}
        return kwargs

    def form_valid(self, form):
        form.instance.user = self.request.user
        review = form.save()
        messages.success(
            self.request,
            _("Your comment has been submitted and will be displayed after approval")
        )
        return redirect(
            reverse_lazy(
                "shop:product-detail",
                kwargs={"slug": review.product.slug}
            )
        )

    def form_invalid(self, form):
        for errors in form.errors.values():
            for error in errors:
                messages.error(self.request, error)
        return redirect(self.request.META.get("HTTP_REFERER"))
