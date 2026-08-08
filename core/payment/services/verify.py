# payment/services/verify.py
from django.db import transaction
from django.core.exceptions import ValidationError
from payment.services.gateway_service import GatewayService
from payment.enums import PaymentStatusType
from payment.repositories.payment_repository import PaymentRepository
from payment.policies import PaymentPolicy

from order.services.confirm_payment import confirm_order_payment
from django.utils.translation import gettext_lazy as _

@transaction.atomic
def verify_payment(*, authority, ref_id, response=None):
    """
    Idempotent payment verification
    """
    payment = PaymentRepository.by_authority_for_update(authority)
    result = GatewayService.verify(payment)

    if not payment.is_verified:
        PaymentPolicy.can_verify(payment)
        
        payment = payment.mark_success(
        ref_id=ref_id,
        gateway_transaction_id=result.transaction_id,
        response=response,
        )

    confirm_order_payment(order_id=payment.order_id)

    return payment
