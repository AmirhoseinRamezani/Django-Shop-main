from django.core.exceptions import ValidationError
from payment.models import PaymentStatusType
from order.models import OrderStatusType


class PaymentPolicy:

    @staticmethod
    def can_start_payment(order):
        """
        آیا اجازه داریم برای این سفارش پرداخت جدید بسازیم؟
        """

        if order.status != OrderStatusType.pending:
            raise ValidationError("امکان پرداخت برای این سفارش وجود ندارد")

        if order.is_expired():
            raise ValidationError("این سفارش منقضی شده است")

        active_payment_exists = order.payments.filter(
            status=PaymentStatusType.pending
        ).exists()

        if active_payment_exists:
            raise ValidationError("پرداخت فعال برای این سفارش وجود دارد")