# tests/builders/payment_builder.py
from payment.models import PaymentStatusType
from tests.factories.payment import PaymentFactory


class PaymentBuilder:

    def __init__(self, order):
        self.order = order
        self.kwargs = {}

    @classmethod
    def for_order(cls, order):
        return cls(order)

    def pending(self):
        self.kwargs["status"] = PaymentStatusType.pending
        return self

    def success(self):
        self.kwargs["status"] = PaymentStatusType.success
        return self

    def failed(self):
        self.kwargs["status"] = PaymentStatusType.failed
        return self

    def consumed(self):
        self.kwargs["is_consumed"] = True
        return self

    def amount(self, value):
        self.kwargs["amount"] = value
        return self

    def build(self):
        return PaymentFactory(
            order=self.order,
            **self.kwargs,
        )