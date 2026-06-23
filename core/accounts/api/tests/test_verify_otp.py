# accounts/api/tests/test_verify_otp.py
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from accounts.models.otp import EmailOTP, OTPPurpose
from django.utils import timezone
from django.contrib.auth.hashers import make_password

User = get_user_model()


class VerifyOTPAPITest(APITestCase):

    def setUp(self):
                    
        self.url = "/api/accounts/otp/verify/"
        self.email = "x@test.com"
        self.code = "1234"

        self.otp = EmailOTP.objects.create(
            email=self.email,
            purpose=OTPPurpose.SIGNUP,
            code_hash=make_password(self.code),
            expire_at=timezone.now() + timezone.timedelta(minutes=2),
        )

    def test_verify_invalid_code(self):
        res = self.client.post(self.url, {
            "email": self.email,
            "code": "0000",
            "purpose": "signup",
        })

        self.assertEqual(res.status_code, 400)

    def test_verify_valid_signup_flow(self):
        res = self.client.post(self.url, {
            "email": self.email,
            "code": self.code,
            "purpose": "signup",
        })

        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)

        user = User.objects.get(email=self.email)
        self.assertTrue(user.is_verified)
