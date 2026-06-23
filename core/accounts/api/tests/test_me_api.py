# accounts/api/tests/test_me_api.py
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from accounts.services.jwt import create_access_token
from accounts.models.device_session import DeviceSession

User = get_user_model()


class MeAPITest(APITestCase):

    def setUp(self):
        self.user = User.objects.create(
            email="test@test.com",
            is_active=True,
            is_verified=True,
        )
        self.session = DeviceSession.objects.create(
            user=self.user,
            device_hash="test-device",
            ip_address="127.0.0.1",
            user_agent="pytest",
        )
        self.token = create_access_token(
            user_id=self.user.id,
            session_id=self.session.id,
        )
        self.url = "/api/accounts/me/"
                    
    def test_me_requires_auth(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 401)

    def test_me_authenticated(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.token}"
        )
        res = self.client.get(self.url)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["email"], self.user.email)
