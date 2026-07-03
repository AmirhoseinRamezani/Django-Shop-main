# payment/policies.py
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from payment.models import PaymentStatusType
from order.models import OrderStatusType


class PaymentPolicy:

    @staticmethod
    def can_start_payment(order):
        """
        آیا اجازه داریم برای این سفارش پرداخت جدید بسازیم؟
        """

        # if order.status != OrderStatusType.pending:
        if order.status not in {
            OrderStatusType.pending,
            OrderStatusType.failed,
        }:
            raise ValidationError(_("Payment is not possible for this order"))

        if order.is_expired():
            raise ValidationError(_("This order has expired"))

        if order.has_pending_payment():
            raise ValidationError(_("A pending payment already exists."))

        return True
    
        # active_payment_exists = order.payments.filter(
        #     status=PaymentStatusType.pending
        # ).exists()

        # if active_payment_exists:
        #     raise ValidationError(_("There is an active payment for this order"))
        
    @staticmethod
    def can_refund(payment):
        if payment.status != PaymentStatusType.success:
            raise ValidationError(_("Payment not successful"))

        if payment.is_refunded:
            raise ValidationError(_("This payment has already been refunded"))

        return True
    