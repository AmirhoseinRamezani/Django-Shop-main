# accounts/validators.py
import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

def validate_iranian_cellphone_number(value: str):
    """
    Validate Iranian cellphone numbers.

    Accepted format:
    - Starts with 09
    - Exactly 11 digits
    Example: 09123456789
    """
    pattern = r'^09\d{9}$'

    if not re.match(pattern, value):
        raise ValidationError(
            _("The mobile number entered is not valid."),
            code="invalid_phone_number"
        )
