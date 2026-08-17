# payment/services/factory.py
import secrets
from django.conf import settings
from payment.models import PaymentModel
from payment.enums import PaymentStatusType, PaymentGateway


class PaymentFactory:

    @staticmethod
    def create(
        *,
        order,
        amount,
        authority_id=None,
        request_payload=None,
        response_payload=None,
        meta=None,
        gateway=None,
        status=PaymentStatusType.PENDING,
    ):
        """
        Create a new payment record with a secure authority_id.
        """

        return PaymentModel.objects.create(
            order=order,
            authority_id=authority_id or secrets.token_hex(32),
            amount=amount,
            gateway=gateway or settings.DEFAULT_PAYMENT_GATEWAY,
            status=status,
            currency=settings.DEFAULT_CURRENCY,
            request_payload=request_payload or {},
            response_payload=response_payload or {},
            meta=meta or {},
        )
