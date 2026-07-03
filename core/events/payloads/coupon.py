# events/payloads/coupon.py

from dataclasses import dataclass


@dataclass(slots=True)
class CouponPayload:

    email: str

    code: str