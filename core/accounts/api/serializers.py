# accounts/api/serializers.py

from rest_framework import serializers
from accounts.models import OTPPurpose


class RequestOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    purpose = serializers.ChoiceField(choices=OTPPurpose.choices)


class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(min_length=4, max_length=6)
    purpose = serializers.ChoiceField(choices=OTPPurpose.choices)
