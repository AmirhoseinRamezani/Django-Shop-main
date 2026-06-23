# from django.db import transaction

# from payment.models import PaymentModel, PaymentStatusType
# from payment.policies import PaymentPolicy
# from order.models import OrderStatusType
# from order.events.order_event import OrderEventType
# from order.services.events import record_order_event

# @transaction.atomic
# def refund_payment(*, payment_id: int, actor) -> PaymentModel:

#     payment = (
#         PaymentModel.objects
#         .select_for_update()
#         .get(id=payment_id)
#     )

#     PaymentPolicy.can_refund(payment)

#     # --- Refund ---
#     payment.status = PaymentStatusType.refunded
#     payment.is_refunded = True
#     payment.save(update_fields=["status", "is_refunded"])

#     order = payment.order

#     order.status = OrderStatusType.refunded
#     order.save(update_fields=["status"])

#     record_order_event(
#         order=order,
#         type=OrderEventType.REFUNDED,
#         actor=actor,
#         payload={
#             "payment_id": payment.id,
#             "amount": str(payment.amount),
#         },
#     )

#     return payment

#     """
#          نکته‌های ظریف این کد:

#         atomic

#         idempotency با Policy

#         هیچ gateway اینجا نیست

#         order فقط update می‌شود، نه «تصمیم‌گیر»
#     """