# payment/policies.py
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from payment.enums import PaymentStatusType
from order.models import OrderStatusType


class PaymentPolicy:

    @staticmethod
    def can_start_payment(order):
        """
        آیا اجازه داریم برای این سفارش پرداخت جدید بسازیم؟
        """

        if order.status != OrderStatusType.pending:
        # if order.status not in {
        #     OrderStatusType.pending,
        #     OrderStatusType.failed,
        # }:
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
        
        if not payment.can_refund:
            raise ValidationError(_("This payment cannot be refunded"))
        # if payment.status != PaymentStatusType.success:
        #     raise ValidationError(_("Payment not successful"))

        # if payment.is_refunded:
        #     raise ValidationError(_("This payment has already been refunded"))
        
        # if not payment.is_consumed:
        #     raise ValidationError(_("Payment has not finalized an order"))
        
        # if payment.order.status != OrderStatusType.paid:
        #     raise ValidationError(_("Only paid orders can be refunded."))

        return True
    
    @staticmethod
    def can_verify(payment):

        if not payment.can_verify:

            raise ValidationError(_("This payment cannot be verified."))

        return True

    @staticmethod
    def can_retry(payment):

        if not payment.can_retry:

            raise ValidationError(_("This payment cannot be retried."))

        return True