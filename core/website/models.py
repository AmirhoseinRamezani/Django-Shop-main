from django.db import models
from django.utils.translation import gettext_lazy as _


class Contact(models.Model):
    """
    Stores contact form submissions from users.
    This model is intentionally independent from User
    to allow anonymous tickets.
    """
    full_name = models.CharField(_("Full name"), max_length=200)
    email = models.EmailField(_("Email address"), blank=True, null=True)
    phone_number = models.CharField(_("Phone number"), max_length=15, blank=True, null=True)
    subject = models.CharField(_("Subject"), max_length=200, blank=True, null=True)
    content = models.TextField(_("Message content"), max_length=700)

    is_seen = models.BooleanField(_("Seen by admin"), default=False)

    created_date = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_date = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        ordering = ["-created_date"]
        verbose_name = _("Contact ticket")
        verbose_name_plural = _("Contact tickets")
        indexes = [
            models.Index(fields=["is_seen"]),
            models.Index(fields=["created_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} - {self.subject or 'No subject'}"


class Newsletter(models.Model):
    """
    Stores newsletter subscribers.
    Email must be unique to avoid duplicates.
    """

    email = models.EmailField(_("Email address"), unique=True)
    created_date = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Newsletter subscriber")
        verbose_name_plural = _("Newsletter subscribers")

    def __str__(self) -> str:
        return self.email
