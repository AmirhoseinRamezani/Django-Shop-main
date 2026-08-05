# # payment/test/test_payment_idempotency.py
# import pytest
# from django.core.exceptions import ValidationError

# from order.services.confirm_payment import confirm_order_payment


# def test_payment_cannot_be_consumed_twice(
#     pending_order,
#     successful_payment
# ):
#     confirm_order_payment(pending_order.id)

#     with pytest.raises(ValidationError):
#         confirm_order_payment(pending_order.id)
