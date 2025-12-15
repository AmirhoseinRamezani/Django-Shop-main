from django.contrib.auth import forms as auth_forms
from django.core.exceptions import ValidationError


class AuthenticationForm(auth_forms.AuthenticationForm):
    """
    Custom authentication form.

    This class extends Django's default AuthenticationForm
    and allows us to enforce additional login policies such as:
    - verified users only
    - store-based access control (future)
    """

    def confirm_login_allowed(self, user):
        """
        This method is called after the user credentials
        have been validated.

        Here we can block login based on business rules
        without touching the authentication backend.
        """
        super().confirm_login_allowed(user)

        # Example: prevent login for unverified users
        # This is intentionally commented out for phase 1
        # but left here as a clear extension point.
        #
        # if not user.is_verified:
        #     raise ValidationError(
        #         "حساب کاربری شما هنوز تایید نشده است.",
        #         code="inactive"
        #     )
