# tests/integration/order/test_concurrency.py
import threading

from django.test import TransactionTestCase

from django.core.exceptions import ValidationError

from order.services.confirm_payment import (
    confirm_order_payment,
)


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
        )

        self.payment = (
            PaymentBuilder()
            .for_order(self.order)
            .success()
            .build()
        )

    def worker(self, errors):

        try:
            confirm_order_payment(self.order.id)

        except Exception as exc:
            errors.append(exc)

    def test_only_one_confirmation(self):

        errors = []

        t1 = threading.Thread(
            target=self.worker,
            args=(errors,),
        )

        t2 = threading.Thread(
            target=self.worker,
            args=(errors,),
        )

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        self.payment.refresh_from_db()

        self.assertTrue(self.payment.is_consumed)

        self.assertEqual(len(errors), 1)

        self.assertIsInstance(
            errors[0],
            ValidationError,
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
        )

        PaymentBuilder()\
            .for_order(self.order)\
            .success()\
            .build()

    def worker(self):

        try:
            confirm_order_payment(self.order.id)
        except Exception:
            pass

    def test_coupon_used_once(self):

        t1 = threading.Thread(target=self.worker)
        t2 = threading.Thread(target=self.worker)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        self.coupon.refresh_from_db()

        self.assertEqual(
            self.coupon.used_count,
            1,
        )
        
        
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
        )

        PaymentBuilder()\
            .for_order(self.order)\
            .success()\
            .build()

    def worker(self):

        try:
            confirm_order_payment(self.order.id)
        except Exception:
            pass

    def test_order_paid_once(self):

        threads = [
            threading.Thread(target=self.worker)
            for _ in range(5)
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.order.refresh_from_db()

        self.assertEqual(
            self.order.status,
            self.order.status.paid,
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

        self.user = UserBuilder().build()

        self.product = (
            ProductBuilder()
            .stock(1)
            .build()
        )

        self.address = (
            AddressBuilder()
            .for_user(self.user)
            .build()
        )

    def create_order(self, errors):

        from tests.builders import CartBuilder

        cart = (
            CartBuilder()
            .for_user(self.user)
            .add(
                self.product,
                quantity=1,
            )
            .build()
        )

        try:

            OrderService.create_online_order(
                user=self.user,
                address=self.address,
                cart=cart,
            )

        except Exception as exc:

            errors.append(exc)

    def test_stock_never_negative(self):

        errors = []

        t1 = threading.Thread(
            target=self.create_order,
            args=(errors,),
        )

        t2 = threading.Thread(
            target=self.create_order,
            args=(errors,),
        )

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        self.product.refresh_from_db()

        self.assertEqual(
            self.product.stock,
            0,
        )

        self.assertEqual(
            len(errors),
            1,
        )