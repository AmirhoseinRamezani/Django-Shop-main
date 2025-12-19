from payment.models import PaymentModel
from payment.zarinpal_client import ZarinPalSandbox


class PaymentService:

    @staticmethod
    def start_payment(order):
        zarinpal = ZarinPalSandbox()
        response = zarinpal.payment_request(order.get_payable_price())

        payment = PaymentModel.objects.create(
            authority_id=response["Authority"],
            amount=order.get_payable_price(),
            response_json=response
        )

        order.payment = payment
        order.save()

        return zarinpal.generate_payment_url(payment.authority_id)
