# payment/services/gateway_service.py

from payment.models import PaymentModel
from payment.zarinpal_client import ZarinPalSandbox

class GatewayService:

    @staticmethod
    def verify(payment):
        zarinpal = ZarinPalSandbox()

        return zarinpal.verify_payment(
            int(payment.amount),
            payment.authority_id,
        )