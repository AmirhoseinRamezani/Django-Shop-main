from django import forms
from .models import Contact, Newsletter
from django.core.exceptions import ValidationError

from django.utils.translation import gettext_lazy as _

class ContactForm(forms.ModelForm):
    """
    Contact form used in public website.
    """

    class Meta:
        model = Contact
        fields = ["full_name", "email", "phone_number", "subject", "content"]

        error_messages = {
            "full_name": {
                "required": _("First and last name are required"),
            },
            "email": {
                "invalid": _("The email entered is not valid"),
            },
            "content": {
                "required": _("Message text cannot be empty"),
            },
        }


class NewsletterForm(forms.ModelForm):
    """
    Newsletter subscription form with honeypot field
    to block bots.
    """

    # Honeypot field (must stay empty)
    first_name = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Newsletter
        fields = ["email", "first_name"]

    def clean_first_name(self):
        """
        If this field is filled, it's almost certainly a bot.
        """
        if self.cleaned_data.get("first_name"):
            raise forms.ValidationError(_("Invalid request."))
        return self.cleaned_data["first_name"]

    def save(self, commit=True):
        """
        Prevent duplicate emails by using get_or_create.
        """
        newsletter, _ = Newsletter.objects.get_or_create(
            email=self.cleaned_data["email"]
        )
        return newsletter
