# tests/integration/order/test_concurrency.py
from __future__ import annotations
import threading

import pytest
from django.test import TransactionTestCase

from order.models import OrderStatusType
from order.services.confirm_payment import (
    confirm_order_payment,
)
from order.services.order import OrderService


class ConfirmPaymentConcurrencyTests(TransactionTestCase):

    reset_sequences = True

    def setUp(self):
        from tests.builders import (
            UserBuilder,
            OrderBuilder,
            PaymentBuilder,
        )

        self.user = UserBuilder().build()

        self.order = (
            OrderBuilder()
            .for_user(self.user)
            .pending()
            .build()
            .order
        )

        self.payment = (
            PaymentBuilder()
            .for_order(self.order)
            .success()
            .successful_attempt()
            .build()
            .payment
        )

    def worker(
        self,
        *,
        barrier: threading.Barrier,
        errors: list[BaseException],
    ):
        barrier.wait()

        try:
            confirm_order_payment(
                self.order.id,
                payment_id=self.payment.id,
            )
            
        except BaseException as exc:
            errors.append(exc)

    def test_only_one_confirmation(self):

        """
        Two workers must race on the same exact Payment.

        The barrier synchronizes entry into the confirmation workflow.
        PostgreSQL row locking remains responsible for serialization.
        """

        errors: list[BaseException] = []
        barrier = threading.Barrier(2)

        threads = [
            threading.Thread(
                target=self.worker,
                kwargs={
                    "barrier": barrier,
                    "errors": errors,
                },
            )
            for _ in range(2)
        ]
        
        for thread in threads:
            thread.start()
            
        for thread in threads:
            thread.join()
        
        if errors:
            pytest.fail(
                "Concurrent confirmation raised unexpected exceptions: "
                f"{errors!r}"
            )
        
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        
        self.assertTrue(self.payment.is_consumed)
        self.assertEqual(
            self.order.status,
            OrderStatusType.paid,
            )
    
class CouponConsumeConcurrencyTests(TransactionTestCase):

    reset_sequences = True

    def setUp(self):

        from tests.builders import (
            UserBuilder,
            CouponBuilder,
            OrderBuilder,
            PaymentBuilder,
        )

        self.user = UserBuilder().build()

        self.coupon = CouponBuilder().build()

        self.order = (
            OrderBuilder()
            .for_user(self.user)
            .with_coupon(self.coupon)
            .pending()
            .build()
            .order
        )

        (
            PaymentBuilder()
            .for_order(self.order)
            .success()
            .successful_attempt()
            .build()
        )

    def worker(
        self,
        *,
        barrier: threading.Barrier,
        errors: list[BaseException],
    ):
        barrier.wait()

        try:
            confirm_order_payment(self.order.id)
        except BaseException as exc:
            errors.append(exc)

    def test_coupon_used_once(self):
        errors: list[BaseException] = []
        barrier = threading.Barrier(2)
        
        threads = [
            threading.Thread(
                target=self.worker,
                kwargs={
                    "barrier": barrier,
                    "errors": errors,
                },
            )
            for _ in range(2)
        ]
        
        for thread in threads:
            thread.start()
            
        for thread in threads:
            thread.join()
            
        if errors:
            pytest.fail(
                "Concurrent coupon finalization raised exceptions: "
                f"{errors!r}"
            )
        
        self.coupon.refresh_from_db()
        
        self.assertEqual( self.coupon.used_count ,1 )
        
        
class OrderStatusConcurrencyTests(TransactionTestCase):

    reset_sequences = True

    def setUp(self):

        from tests.builders import (
            UserBuilder,
            OrderBuilder,
            PaymentBuilder,
        )

        user = UserBuilder().build()

        self.order = (
            OrderBuilder()
            .for_user(user)
            .pending()
            .build()
            .order
        )

        (
            PaymentBuilder()
            .for_order(self.order)
            .success()
            .successful_attempt()
            .build()
        )

    def worker(
        self,
        *,
        barrier: threading.Barrier,
        errors: list[BaseException],
    ):
        barrier.wait()

        try:
            confirm_order_payment(self.order.id)
        except BaseException as exc:
            errors.append(exc)

    def test_order_paid_once(self):
        errors: list[BaseException] = []
        barrier = threading.Barrier(5)
        
        threads = [
            threading.Thread(
                target=self.worker,
                kwargs={
                    "barrier": barrier,
                    "errors": errors,
                },
            )
            for _ in range(5)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()
            
        if errors:
            pytest.fail(
                "Concurrent order finalization raised exceptions: "
                f"{errors!r}"
            )

        self.order.refresh_from_db()

        self.assertEqual(
            self.order.status,
            OrderStatusType.paid,
        )
        
class StockConcurrencyTests(TransactionTestCase):

    reset_sequences = True

    def setUp(self):

        from tests.builders import (
            UserBuilder,
            ProductBuilder,
            CartBuilder,
            AddressBuilder,
        )

        self.users = [
            UserBuilder().build(),
            UserBuilder().build(),
        ]

        self.product = (
            ProductBuilder()
            .stock(1)
            .build()
        )

        self.addresses = [
            AddressBuilder()
            .for_user(user)
            .build()
            for user in self.users
        ]

    def create_order(self, user, address, barrier, errors):

        from tests.builders import CartBuilder

        cart = (
            CartBuilder()
            .for_user(user)
            .add(
                self.product,
                quantity=1,
            )
            .build()
        )

        barrier.wait()

        try:

            OrderService.create_online_order(
                user=user,
                address=address,
                cart=cart,
            )

        except Exception as exc:

            errors.append(exc)

    def test_stock_never_negative(self):

        errors = []
        barrier = threading.Barrier(2)

        threads = [
            threading.Thread(
                target=self.create_order,
                args=(
                    self.users[index],
                    self.addresses[index],
                    barrier,
                    errors,
                ),
            )
            for index in range(2)
        ]
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join()
        
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)
        self.assertEqual(len(errors), 1)

        