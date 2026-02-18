class OTPThrottleException(Exception):
    """
    Raised when OTP request rate exceeds allowed limits.
    """
    pass
