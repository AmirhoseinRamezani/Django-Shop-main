# # payment/test/test_payment_expired_order.py
# from django.utils import timezone
# from order.services.confirm_payment import confirm_order_payment
# import pytest

# def test_expired_order_cannot_be_paid(
#     pending_order,
#     successful_payment,
# ):
#     pending_order.expire_at = timezone.now() - timezone.timedelta(minutes=1)
#     pending_order.save(update_fields=["expire_at"])

#     with pytest.raises(ValueError):
#         confirm_order_payment(pending_order.id)
