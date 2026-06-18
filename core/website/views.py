from django.views.generic import TemplateView, CreateView
from django.contrib import messages
from django.shortcuts import redirect

from .forms import ContactForm, NewsletterForm
from django.utils.translation import gettext_lazy as _

class IndexView(TemplateView):
    """
    Homepage view.
    """
    template_name = "website/index.html"


class ContactView(TemplateView):
    """
    Contact page (GET request only).
    """
    template_name = "website/contact.html"


class AboutView(TemplateView):
    """
    About us page.
    """
    template_name = "website/about.html"


class SendContactView(CreateView):
    """
    Handles contact form submission.
    Only POST requests are allowed.
    """

    form_class = ContactForm
    http_method_names = ["post"]

    def form_valid(self, form):
        form.save()
        messages.success(
            self.request,
            _("Your message has been successfully submitted and will be reviewed shortly."),
        )
        return redirect(self.request.META.get("HTTP_REFERER", "/"))

    def form_invalid(self, form):
        messages.error(
            self.request,
            _("An error occurred while sending the message. Please check your entries."),
        )
        return redirect(self.request.META.get("HTTP_REFERER", "/"))


class NewsletterView(CreateView):
    """
    Handles newsletter subscriptions.
    """

    form_class = NewsletterForm
    http_method_names = ["post"]

    def form_valid(self, form):
        form.save()
        messages.success(
            self.request,
            _("Your subscription to the newsletter has been successful.🎉"),
        )
        return redirect("website:index")

    def form_invalid(self, form):
        messages.error(
            self.request,
            _("Invalid request detected."),
        )
        return redirect("website:index")
