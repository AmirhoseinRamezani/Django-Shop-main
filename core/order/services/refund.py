# # order/services/refund.py
# from django.db import transaction
# from django.core.exceptions import ValidationError
# from payment.models import PaymentStatusType
# from order.models import OrderStatusType
# from order.events.order_event import OrderEventType
# # from order.services.events import record_order_event
# from order.services.state_machine import OrderStateMachine
# from django.utils.translation import gettext as _


# class RefundService:

#     @staticmethod
#     @transaction.atomic
#     def refund_order(order, *, admin_user):
#         if not order.can_refund():
#             raise ValidationError(_("This order is non-refundable"))

#         payment = (
#             order.payments
#             .filter(
#                 status=PaymentStatusType.success
#             )
#             .order_by("-created_date")
#             .first()
#         )
#         if not payment:
#             raise ValidationError(_("There is no payment for this order"))
        
#         # In real gateway: call refund API here
#         payment.status = PaymentStatusType.failed
#         # order.status = OrderStatusType.refunded

#         payment.save(update_fields=["status"])
#         # order.save(update_fields=["status"])

#         OrderStateMachine.transition(
#             order=order,
#             to_status=OrderStatusType.refunded,
#             actor=admin_user,
#         )

#         # record_order_event(
#         #     order=order,
#         #     type=OrderEventType.REFUNDED,
#         #     actor=admin_user,
#         # )
#         return order
    
#     # @property
#     # def can_refund(self):
#     #     return self.status == OrderStatusType.success

