import requests
from django.conf import settings


def get_domain():
    """
    Safe domain resolver.
    Works before migrations and without breaking makemigrations.
    """
    try:
        from django.contrib.sites.models import Site
        return Site.objects.get_current().domain
    except Exception:
        return "localhost:8000"


def get_protocol():
    return "https" if getattr(settings, "SECURE_SSL_REDIRECT", False) else "http"


class ZarinPalSandbox:
    """
    ZarinPal Sandbox client
    Compatible with docker, sites framework and pre-migration state
    """

    PAYMENT_REQUEST_URL = "https://sandbox.zarinpal.com/pg/rest/WebGate/PaymentRequest.json"
    PAYMENT_VERIFY_URL = "https://sandbox.zarinpal.com/pg/rest/WebGate/PaymentVerification.json"
    PAYMENT_PAGE_URL = "https://sandbox.zarinpal.com/pg/StartPay/"

    def __init__(self):
        self.merchant_id = settings.MERCHANT_ID
        self.callback_url = f"{get_protocol()}://{get_domain()}/payment/verify"

    def payment_request(self, amount, description="پرداختی کاربر"):
        payload = {
            "MerchantID": self.merchant_id,
            "Amount": str(amount),
            "CallbackURL": self.callback_url,
            "Description": description,
        }
        return requests.post(self.PAYMENT_REQUEST_URL, json=payload).json()

    def payment_verify(self, amount, authority):
        payload = {
            "MerchantID": self.merchant_id,
            "Amount": amount,
            "Authority": authority,
        }
        return requests.post(self.PAYMENT_VERIFY_URL, json=payload).json()

    def generate_payment_url(self, authority):
        return f"{self.PAYMENT_PAGE_URL}{authority}"
