from django.db import transaction
from django.core.exceptions import ValidationError
from payment.models import PaymentStatusType
from order.models import OrderStatusType

class RefundService:

    @staticmethod
    @transaction.atomic
    def refund_order(order, *, admin_user):
        if not order.can_refund():
            raise ValidationError("این سفارش قابل بازگشت وجه نیست")

        payment = order.payment
        if not payment:
            raise ValidationError("پرداختی برای این سفارش وجود ندارد")
        
        # In real gateway: call refund API here
        payment.status = PaymentStatusType.failed
        order.status = OrderStatusType.refunded

        payment.save(update_fields=["status"])
        order.save(update_fields=["status"])

        return order
    
    @property
    def can_refund(self):
        return self.status == OrderStatusType.success