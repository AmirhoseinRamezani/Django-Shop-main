import requests
from django.conf import settings


class ZarinPalSandbox:
    """
    Sandbox gateway – replace URLs for production
    """

    PAYMENT_REQUEST_URL = "https://sandbox.zarinpal.com/pg/rest/WebGate/PaymentRequest.json"
    PAYMENT_VERIFY_URL = "https://sandbox.zarinpal.com/pg/rest/WebGate/PaymentVerification.json"
    PAYMENT_PAGE_URL = "https://sandbox.zarinpal.com/pg/StartPay/"

    CALLBACK_URL = f"{settings.SITE_URL}/payment/verify"

    def __init__(self):
        self.merchant_id = settings.MERCHANT_ID

    def payment_request(self, amount, description):
        payload = {
            "MerchantID": self.merchant_id,
            "Amount": str(amount),
            "CallbackURL": self.CALLBACK_URL,
            "Description": description,
        }
        return requests.post(self.PAYMENT_REQUEST_URL, json=payload).json()

    def payment_verify(self, amount, authority):
        payload = {
            "MerchantID": self.merchant_id,
            "Amount": amount,
            "Authority": authority
        }
        return requests.post(self.PAYMENT_VERIFY_URL, json=payload).json()

    def generate_payment_url(self, authority):
        return f"{self.PAYMENT_PAGE_URL}{authority}"
