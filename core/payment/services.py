from django.core.exceptions import PermissionDenied
from .models import PaymentModel
from .zarinpal_client import ZarinPalSandbox


class PaymentService:

    @staticmethod
    def start_payment(order):

        if not order.store.allows_online_payment():
            raise PermissionDenied("This store does not allow online payments")

        zarinpal = ZarinPalSandbox()
        response = zarinpal.payment_request(order.get_payable_price())

        payment = PaymentModel.objects.create(
            authority_id=response["Authority"],
            amount=order.get_payable_price(),
            response_json=response
        )

        order.payment = payment
        order.save(update_fields=["payment"])

        return zarinpal.generate_payment_url(payment.authority_id)
