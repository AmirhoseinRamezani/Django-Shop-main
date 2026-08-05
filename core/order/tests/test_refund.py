# # order/tests/test_refund.py
# import pytest

# from order.services.refund import RefundService

# from order.models import (
#     OrderStatusType
# )


# @pytest.mark.django_db
# def test_refund_paid_order(
#     successful_payment,
#     pending_order,
#     user,
#     admin_user,
# ):
#     pending_order.status = (
#         OrderStatusType.paid
#     )
#     pending_order.save()

#     RefundService.refund_order(
#         pending_order,
#         admin_user=admin_user,
#     )

#     pending_order.refresh_from_db()

#     assert (
#         pending_order.status
#         == OrderStatusType.refunded
#     )
