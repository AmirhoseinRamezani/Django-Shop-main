# accounts/api/tests/test_otp_throttle.py
from rest_framework.test import APITestCase

class OTPThrottleTest(APITestCase):

    def test_otp_throttle_blocks_spam(self):
        url = "/api/accounts/otp/request/"
            
        payload = {
            "email": "spam@test.com",
            "purpose": "signup",
        }

        for i in range(5):
            self.client.post(url, payload)

        res = self.client.post(url, payload)

        self.assertEqual(res.status_code, 429)
