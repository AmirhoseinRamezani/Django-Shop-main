# payment/services/refund.py
from django.db import transaction

from payment.models import PaymentModel
from payment.services.gateway_service import GatewayService

from order.policies.refund import RefundPolicy
from payment.policies import PaymentPolicy

from order.models import (
    OrderStatusType,
)

from order.services.state_machine import (
    OrderStateMachine,
)

class RefundService:

    @staticmethod
    @transaction.atomic
    def refund(
        *,
        payment_id: int,
        actor,
    ):

        payment = (
            PaymentModel.objects
            .select_for_update()
            .select_related(
                "order",
            )
            .get(
                id=payment_id,
            )
        )

        PaymentPolicy.can_refund(payment)

        order = payment.order

        # -----------------------------
        # Gateway Refund
        # -----------------------------
        #
        # Future:
        #
        # gateway.refund(
        #     payment.ref_id
        # )
        # gateway = GatewayService()

        # gateway.refund(payment)
        # -----------------------------
        
        # payment.mark_refunded()
        result = GatewayService.refund(payment)
        
        payment.mark_refunded(
            refund_ref_id=result.get("ref_id"),
            refunded_by=actor,
            response=result,
        )

        RefundPolicy.rollback_coupon(
            order,
        )
        OrderStateMachine.transition(

            order=order,
            to_status=OrderStatusType.refunded,
            actor=actor,

            payload={
                "payment_id": payment.id,
                "amount": str(payment.amount),
                "ref_id": payment.ref_id,
            }
        )

        return payment
    