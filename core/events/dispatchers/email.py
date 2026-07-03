# events/dispatchers/email.py
from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import ValidationError

from events.clients.email import EmailClient


def send_email_event(event):

    handlers = {

        "user.otp": send_otp_email,
        
        "order.created": send_order_created,

        "order.paid": send_order_paid_email,

        "coupon.used": send_coupon_email,

    }

    handler = handlers.get(event.topic)

    if handler:

        handler(event.payload)


def send_otp(payload):

    email = payload.get("email")

    code = payload.get("code")

    if not email or not code:

        raise ValidationError("OTP payload invalid")

    EmailClient.send(

        subject="کد تایید",

        message=f"کد تایید شما : {code}",

        recipients=[email],

    )


def send_order_created(payload):

    EmailClient.send(

        subject="ثبت سفارش",

        message=f"سفارش شما ثبت شد.",

        recipients=[payload["email"]],

    )


def send_order_paid(payload):

    EmailClient.send(

        subject="پرداخت موفق",

        message=f"پرداخت سفارش {payload['order_id']} با موفقیت انجام شد.",

        recipients=[payload["email"]],

    )


def send_coupon_used(payload):

    EmailClient.send(

        subject="Coupon",

        message="Coupon consumed.",

        recipients=[payload["email"]],

    )