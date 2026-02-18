# events/services/dispatchers/email.py
from django.core.mail import send_mail
from django.conf import settings
from django.core.exceptions import ValidationError

"""
Email dispatcher for Outbox events.

Only responsibility:
- Transform event payload
- Send email
"""
def send_email_event(event):
    """
    Entry point for all email-related events.
    """
    handlers = {
        "user.otp": _send_otp_email,
    }
    
    handler = handlers.get(event.topic)
    if not handler:
        return
    

    handler(event.payload)


def _send_otp_email(payload: dict):
    """
    Send OTP email to user.
    Payload schema:
        {
            "email": str,
            "code": str,
            "purpose": str
        }
    """
    email = payload.get("email")
    code = payload.get("code")

    if not email or not code:
        raise ValidationError("OTP payload is missing required fields")
    
    send_mail(
        subject="کد تایید ورود",
        message=f"کد تایید شما: {code}\n\nاین کد ۲ دقیقه اعتبار دارد.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )
