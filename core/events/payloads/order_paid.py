# events/payloads/order_paid.py
from dataclasses import dataclass


@dataclass(slots=True)
class OrderPaidPayload:

    order_id: int

    amount: int

    email: str