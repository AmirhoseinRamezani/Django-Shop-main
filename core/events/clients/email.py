# events/clients/email.py
from django.conf import settings
from django.core.mail import send_mail


class EmailClient:

    @staticmethod
    def send(
        *,
        subject: str,
        message: str,
        recipients: list[str],
    ) -> None:

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )