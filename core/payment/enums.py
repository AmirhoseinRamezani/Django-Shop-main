# payment/enums.py
from django.db import models
from django.utils.translation import gettext_lazy as _


class PaymentStatusType(models.IntegerChoices):
    PENDING = 1, _("Pending")
    SUCCESS = 2, _("Successful")
    FAILED = 3, _("Failed")

class PaymentAttemptStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")
    TIMEOUT = "timeout", _("Timeout")
    CANCELLED = "cancelled", _("Cancelled")

class RefundStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")

class GatewayLogType(models.TextChoices):
    REQUEST = "request", _("Request")
    RESPONSE = "response", _("Response")
    CALLBACK = "callback", _("Callback")
    VERIFY = "verify", _("Verify")
    REFUND = "refund", _("Refund")
    WEBHOOK = "webhook", _("Webhook")
    ERROR = "error", _("Error")

class GatewayLogDirection(models.TextChoices):
    OUTBOUND = "outbound", _("Outbound")
    INBOUND = "inbound", _("Inbound")

class PaymentGateway(models.TextChoices):
    ZARINPAL = "zarinpal", _("Zarinpal")
    STRIPE = "stripe", _("Stripe")
    PAYPAL = "paypal", _("Paypal")
    MELLAT = "mellat", _("Mellat")
    UNKNOWN = "unknown", _("Unknown")

class Currency(models.TextChoices):
    IRR = "IRR", "IRR"
    # IRT = "IRT", "IRT"
    # USD = "USD", "USD"
    
class RefundReason(models.TextChoices):
    CUSTOMER_REQUEST = "customer_request", _("Customer Request")
    ADMIN = "admin", _("Admin")
    FRAUD = "fraud", _("Fraud")
    DUPLICATE = "duplicate", _("Duplicate Payment")
    FAILED_DELIVERY = "failed_delivery", _("Failed Delivery")
    OTHER = "other", _("Other")