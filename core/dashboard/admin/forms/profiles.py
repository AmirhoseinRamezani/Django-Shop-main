from django.contrib.auth import forms as auth_forms
from django import forms
from django.utils.translation import gettext_lazy as _
from accounts.models import Profile


class AdminPasswordChangeForm(auth_forms.PasswordChangeForm):
    error_messages = {
        "password_incorrect": _(
            "Your previous password was entered incorrectly, please correct it."
        ),
        "password_mismatch": _("The two passwords entered do not match."),
    }
    

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].widget.attrs['class'] = 'form-control text-center'
        self.fields['new_password1'].widget.attrs['class'] = 'form-control text-center'
        self.fields['new_password2'].widget.attrs['class'] = 'form-control text-center'
        self.fields['old_password'].widget.attrs['placeholder'] = "Enter your previous password"
        self.fields['new_password1'].widget.attrs['placeholder'] = "Enter your alternate password"
        self.fields['new_password2'].widget.attrs['placeholder'] = "Re-enter your alternate password"
    

class AdminProfileEditForm(forms.ModelForm):
    class Meta:
        model=Profile
        fields =[
            "first_name",
            "last_name",
            "phone_number"
        ]
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].widget.attrs['class'] = 'form-control'
        self.fields['first_name'].widget.attrs['placeholder'] = 'Enter your name'
        self.fields['last_name'].widget.attrs['class'] = 'form-control '
        self.fields['last_name'].widget.attrs['placeholder'] = 'Enter your last name'
        self.fields['phone_number'].widget.attrs['class'] = 'form-control text-center'
        self.fields['phone_number'].widget.attrs['placeholder'] = 'Enter your mobile number'
        
        