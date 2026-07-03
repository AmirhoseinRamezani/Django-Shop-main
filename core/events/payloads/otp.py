# events/payloads/otp.py
from dataclasses import dataclass


@dataclass(slots=True)
class OTPPayload:

    email: str

    code: str

    purpose: str