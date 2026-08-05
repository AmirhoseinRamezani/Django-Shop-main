# # order/tests/test_order_creation.py
# import pytest

# from django.core.exceptions import ValidationError
# from shop.constants import ProductStatusType
# from order.services.order import OrderService
# from order.models import OrderStatusType
# from order.events.order_event import OrderEventType

# from events.models.outbox import OutboxEvent


# @pytest.mark.django_db
# def test_create_order_success(
#     user,
#     cart,
#     cart_item,
#     address,
# ):
#     order = OrderService.create_online_order(
#         user=user,
#         address=address,
#         cart=cart,
#     )

#     assert order.user == user
#     assert order.status == OrderStatusType.pending
#     assert order.order_items.count() == 1


# @pytest.mark.django_db
# def test_empty_cart(
#     user,
#     cart,
#     address,
# ):
#     with pytest.raises(ValidationError):
#         OrderService.create_online_order(
#             user=user,
#             address=address,
#             cart=cart,
#         )


# @pytest.mark.django_db
# def test_unpublished_product(
#     user,
#     cart,
#     cart_item,
#     address,
#     product,
# ):
    

#     product.status = ProductStatusType.PUBLISH
#     product.save()

#     with pytest.raises(ValidationError):
#         OrderService.create_online_order(
#             user=user,
#             address=address,
#             cart=cart,
#         )


# @pytest.mark.django_db
# def test_insufficient_stock(
#     user,
#     cart,
#     cart_item,
#     address,
#     product,
# ):
#     product.stock = 1
#     product.save()

#     with pytest.raises(ValidationError):
#         OrderService.create_online_order(
#             user=user,
#             address=address,
#             cart=cart,
#         )


# @pytest.mark.django_db
# def test_stock_decrease_after_order(
#     user,
#     cart,
#     cart_item,
#     address,
#     product,
# ):
#     OrderService.create_online_order(
#         user=user,
#         address=address,
#         cart=cart,
#     )

#     product.refresh_from_db()

#     assert product.stock == 8


# @pytest.mark.django_db
# def test_order_created_event(
#     user,
#     cart,
#     cart_item,
#     address,
# ):
#     order = OrderService.create_online_order(
#         user=user,
#         address=address,
#         cart=cart,
#     )

#     assert order.events.filter(
#         type=OrderEventType.CREATED
#     ).exists()


# @pytest.mark.django_db
# def test_outbox_created(
#     user,
#     cart,
#     cart_item,
#     address,
# ):
#     OrderService.create_online_order(
#         user=user,
#         address=address,
#         cart=cart,
#     )

#     assert OutboxEvent.objects.filter(
#         topic="order.created"
#     ).exists()