# payment/services/gateway_service.py
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from payment.enums import PaymentGateway
from types import MappingProxyType

from payment.zarinpal_client import ZarinPalSandbox


class GatewayService:
    
    CLIENTS = MappingProxyType({
        PaymentGateway.ZARINPAL: ZarinPalSandbox,
    })
    """
    Gateway Facade.

    All payment providers must be accessed only
    through this service.

    Future providers:

        - Zarinpal
        - Mellat
        - SEP
        - Stripe
        - Paypal

    """
        
    @classmethod
    def current_gateway(cls):
        """
        Return the active gateway identifier (enum value),
        not the underlying class name.

        This prevents breakage if wrappers or decorators
        are added later.
        """
        return settings.DEFAULT_PAYMENT_GATEWAY
        # return cls._client().__class__.__name__

    # internal
    # ----------------------------------------------
    @classmethod
    def _client(cls,gateway=None):
        """
        Returns active gateway client.

        Future:

            if settings.PAYMENT_GATEWAY == "STRIPE":
                return StripeGateway()

        """
        gateway = gateway or settings.DEFAULT_PAYMENT_GATEWAY
        
        client = cls.CLIENTS.get(gateway)
        if client is None:
            raise ValidationError(_("Gateway client is not active."))
        
        return client()

    # ----------------------------------------------

    @classmethod
    def payment_request(cls, amount, gateway=None):
        client = cls._client(gateway)
        return client.payment_request(amount)

    # ----------------------------------------------

    @classmethod
    def payment_url(cls, authority, gateway=None):
        client = cls._client(gateway)
        return client.generate_payment_url(authority)
    
    # ---------------------------------------------

    @classmethod
    def verify(cls, payment):
        client = cls._client(payment.gateway)
        return client.verify_payment(
            int(payment.amount),
            payment.authority_id,
        )

    # ---------------------------------------------

    @classmethod
    def refund(cls, payment, gateway=None):
        client = cls._client(gateway or payment.gateway)

        if hasattr(client, "refund"):
            return client.refund(payment)

        # Sandbox fallback
        return {
            "success": True,
            "ref_id": f"RF-{payment.ref_id}",
            "gateway": payment.gateway,
            "raw": {},
        }
        