# payment/policies.py
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from payment.enums import PaymentStatusType
from order.models import OrderStatusType


class PaymentPolicy:

    @staticmethod
    def can_start_payment(order):

        if order.status != OrderStatusType.pending:

            raise ValidationError(_("Payment is not possible for this order"))

        if order.is_expired():
            raise ValidationError(_("This order has expired"))

        if order.has_pending_payment():
            raise ValidationError(_("A pending payment already exists."))
        
        return True

    @staticmethod
    def can_refund(payment):
        
        if not payment.can_refund:
            raise ValidationError(_("This payment cannot be refunded"))

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