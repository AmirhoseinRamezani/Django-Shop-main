# tests/builders/event_builder.py
from tests.factories.events import OutboxEventFactory


class EventBuilder:

    def __init__(self):
        self.topic = "test.event"
        self.payload = {}

    @classmethod
    def create(cls):
        return cls()

    def order_created(self, order):

        self.topic = "order.created"

        self.payload = {
            "order_id": order.id,
            "email": order.email,
        }

        return self

    def order_paid(self, order):

        self.topic = "order.paid"

        self.payload = {
            "order_id": order.id,
            "email": order.email,
            "amount": str(order.get_price()),
        }

        return self

    def coupon_used(self, coupon):

        self.topic = "coupon.used"

        self.payload = {
            "code": coupon.code,
        }

        return self

    def otp(self, email, code):

        self.topic = "user.otp"

        self.payload = {
            "email": email,
            "code": code,
        }

        return self

    def build(self):

        return OutboxEventFactory(

            topic=self.topic,

            payload=self.payload,

        )