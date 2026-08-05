# payment/services/verify.py
from django.db import transaction
from django.core.exceptions import ValidationError
from payment.services.gateway_service import GatewayService
# from payment.models import PaymentModel
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
    # payment = PaymentModel.objects.by_authority(authority)
    payment = PaymentRepository.by_authority_for_update(authority)
    # payment = (
    #     PaymentModel.objects
    #     .select_for_update()
    #     .select_related("order")
    #     .get(authority_id=authority)
    # )

    # if payment.status == PaymentStatusType.failed:
    #     raise ValidationError(_("Payment already failed"))

    # Gateway retry (safe)
    # if payment.status == PaymentStatusType.success:
    #     return payment
    
    # if payment.is_verified:
    #     if payment.ref_id != ref_id:
    #         raise ValidationError(_("Reference mismatch."))
    #     return payment
    
    # PaymentPolicy.can_verify(payment)
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
        
        
    # payment = payment.mark_success(
    #     ref_id=ref_id,
    #     gateway_transaction_id=result.transaction_id,
    #     response=response,
    #     )

    