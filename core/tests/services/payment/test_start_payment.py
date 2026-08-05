# # test/services/payment/test_start_payment.py
# import pytest

# from django.core.exceptions import ValidationError

# from payment.models import (
#     PaymentModel,
#     PaymentStatusType,
# )

# from payment.services.services import PaymentService

# pytestmark = pytest.mark.django_db


# class TestStartPayment:

#     def test_create_payment(
#         self,
#         paid_order,
#         mocker,
#     ):
#         gateway = mocker.patch(
#             "payment.services.services.ZarinPalSandbox"
#         )

#         gateway.return_value.payment_request.return_value = {
#             "Authority": "AUTH-1",
#         }

#         gateway.return_value.generate_payment_url.return_value = "url"

#         url = PaymentService.start_payment(
#             paid_order,
#         )

#         payment = PaymentModel.objects.get(
#             order=paid_order,
#         )

#         assert payment.status == PaymentStatusType.pending
#         assert payment.authority_id == "AUTH-1"
#         assert url == "url"

#         gateway.return_value.payment_request.assert_called_once()

#     def test_duplicate_pending_payment(
#         self,
#         paid_order,
#         payment,
#     ):
#         with pytest.raises(ValidationError):
#             PaymentService.start_payment(
#                 paid_order,
#             )

import pytest

from django.core.exceptions import ValidationError

from tests.base import BaseTestCase

from payment.services.services import PaymentService
from payment.models import PaymentModel, PaymentStatusType


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.service,
]


class TestStartPayment(BaseTestCase):

    def test_create_payment(
        self,
        order_factory,
        mocker,
    ):
        gateway = self.gateway(mocker)

        order = order_factory(payable=True)

        url = PaymentService.start_payment(order)

        payment = PaymentModel.objects.get(
            order=order
        )

        self.assert_payment_pending(payment)

        assert payment.amount == order.final_price

        assert payment.authority_id == gateway.authority

        assert url.endswith(payment.authority_id)

    def test_pending_payment_exists(
        self,
        order_factory,
        payment_factory,
    ):
        order = order_factory()

        payment_factory(
            order=order,
            pending=True,
        )

        with pytest.raises(ValidationError):
            PaymentService.start_payment(order)

    def test_expired_order(
        self,
        order_factory,
    ):
        order = order_factory(
            expired=True,
        )

        with pytest.raises(ValidationError):
            PaymentService.start_payment(order)

    def test_cancelled_order(
        self,
        order_factory,
    ):
        order = order_factory(
            cancelled=True,
        )

        with pytest.raises(ValidationError):
            PaymentService.start_payment(order)

    def test_failed_order_can_retry(
        self,
        order_factory,
        mocker,
    ):
        self.gateway(mocker)

        order = order_factory(
            failed=True,
            payable=True,
        )

        PaymentService.start_payment(order)

        assert PaymentModel.objects.filter(
            order=order
        ).count() == 1

    def test_gateway_called_once(
        self,
        order_factory,
        mocker,
    ):
        gateway = self.gateway(mocker)

        order = order_factory()

        PaymentService.start_payment(order)

        gateway.payment_request.assert_called_once()

    def test_amount_equals_final_price(
        self,
        order_factory,
        coupon_factory,
        mocker,
    ):
        self.gateway(mocker)

        coupon = coupon_factory()

        order = order_factory(
            with_coupon=True,
            coupon=coupon,
            coupon_discount_percent=20,
            total_price=100000,
        )

        PaymentService.start_payment(order)

        payment = PaymentModel.objects.get(
            order=order
        )

        assert payment.amount == order.final_price