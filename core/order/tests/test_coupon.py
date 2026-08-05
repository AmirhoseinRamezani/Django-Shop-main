# # order/tests/test_coupon.py
# import pytest

# from order.services.order import OrderService


# @pytest.mark.django_db
# def test_coupon_snapshot_saved(
#     user,
#     cart,
#     cart_item,
#     address,
#     coupon,
# ):
#     order = OrderService.create_online_order(
#         user=user,
#         address=address,
#         cart=cart,
#         coupon=coupon,
#     )

#     assert order.coupon_code == coupon.code

#     assert (
#         order.coupon_discount_percent
#         == coupon.discount_percent
#     )
