# tests/models/test_order.py
import pytest

from django.utils import timezone
from datetime import timedelta

from order.models import OrderStatusType


pytestmark = pytest.mark.django_db


class TestOrderModel:

    def test_get_price_without_coupon(
        self,
        order,
    ):

        assert order.final_price == order.total_price

    def test_get_price_with_coupon(
        self,
        order,
        coupon,
    ):

        order.coupon = coupon
        order.coupon_discount_percent = 20

        assert order.final_price == round(
            order.total_price * 80 / 100
        )

    def test_is_expired(self, order):

        order.expire_at = timezone.now() - timedelta(minutes=1)

        assert order.is_expired() is True

    def test_is_payable(self, order):

        assert order.is_payable is True

    def test_paid_order_not_payable(self, paid_order):

        assert paid_order.is_payable is False

    def test_can_refund_paid(self, paid_order):

        assert paid_order.can_refund() is True

    def test_cancelled_cannot_refund(
        self,
        cancelled_order,
    ):

        assert cancelled_order.can_refund() is False

    def test_last_payment(
        self,
        payment,
        order,
    ):

        assert order.last_payment() == payment

    def test_has_pending_payment(
        self,
        payment,
        order,
    ):

        assert order.has_pending_payment() is True

    def test_mark_failed(self, order):

        order.mark_failed()

        order.refresh_from_db()

        assert order.status == OrderStatusType.failed

    def test_is_paid(self, paid_order):

        assert paid_order.is_paid is True

    def test_is_completed(self, cancelled_order):

        assert cancelled_order.is_completed is True