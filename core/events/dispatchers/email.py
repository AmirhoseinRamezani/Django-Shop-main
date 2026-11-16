# events/dispatchers/email.py

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.exceptions import ObjectDoesNotExist

from events.clients.email import EmailClient


def send_email_event(event) -> None:
    handlers = {
        "user.otp": send_otp_email,
        "order.created": send_order_created,
        "order.paid": send_order_paid_email,
        "coupon.used": send_coupon_email,
    }

    handler = handlers.get(event.topic)
    if handler is not None:
        handler(event.payload)


def _resolve_recipient(payload: dict) -> str:
    if not isinstance(payload, dict):
        raise ValidationError("Email event payload must be an object.")

    email = payload.get("email")
    if isinstance(email, str) and email.strip():
        return email.strip()

    user_id = payload.get("user_id")
    if user_id is None or isinstance(user_id, bool):
        raise ValidationError(
            "Email event requires either email or user_id."
        )

    User = get_user_model()

    try:
        user = User._default_manager.only("email").get(pk=user_id)
    except (ObjectDoesNotExist, ValueError, TypeError) as exc:
        raise ValidationError(
            "Email event recipient could not be resolved."
        ) from exc

    if not isinstance(user.email, str) or not user.email.strip():
        raise ValidationError(
            "Email event recipient has no valid email address."
        )

    return user.email.strip()


def send_otp_email(payload: dict) -> None:
    email = payload.get("email") if isinstance(payload, dict) else None
    code = payload.get("code") if isinstance(payload, dict) else None

    if not isinstance(email, str) or not email.strip() or not code:
        raise ValidationError("OTP payload invalid.")

    EmailClient.send(
        subject="کد تایید",
        message=f"کد تایید شما : {code}",
        recipients=[email.strip()],
    )


def send_order_created(payload: dict) -> None:
    recipient = _resolve_recipient(payload)

    EmailClient.send(
        subject="ثبت سفارش",
        message="سفارش شما ثبت شد.",
        recipients=[recipient],
    )


def send_order_paid_email(payload: dict) -> None:
    recipient = _resolve_recipient(payload)

    order_id = payload.get("order_id")
    if order_id is None:
        raise ValidationError("Order-paid payload requires order_id.")

    EmailClient.send(
        subject="پرداخت موفق",
        message=f"پرداخت سفارش {order_id} با موفقیت انجام شد.",
        recipients=[recipient],
    )


def send_coupon_email(payload: dict) -> None:
    recipient = _resolve_recipient(payload)

    EmailClient.send(
        subject="Coupon",
        message="Coupon consumed.",
        recipients=[recipient],
    )