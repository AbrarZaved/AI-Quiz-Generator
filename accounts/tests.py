from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import OTPCode

User = get_user_model()


class SignupVerifyLoginTests(APITestCase):
    """Covers the signup -> OTP verify -> activate -> login flow."""

    def test_signup_creates_inactive_user_with_otp(self):
        res = self.client.post(
            "/api/auth/signup/",
            {
                "email": "new@example.com",
                "full_name": "New User",
                "password": "strongpass123",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="new@example.com")
        self.assertFalse(user.is_active)
        self.assertTrue(
            OTPCode.objects.filter(
                user=user, purpose=OTPCode.Purpose.EMAIL_VERIFICATION, is_used=False
            ).exists()
        )

    def test_login_blocked_until_verified(self):
        self.client.post(
            "/api/auth/signup/",
            {
                "email": "new@example.com",
                "full_name": "New User",
                "password": "strongpass123",
            },
            format="json",
        )
        # Login before verification is rejected.
        res = self.client.post(
            "/api/auth/login/",
            {"email": "new@example.com", "password": "strongpass123"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_verify_then_login(self):
        self.client.post(
            "/api/auth/signup/",
            {
                "email": "new@example.com",
                "full_name": "New User",
                "password": "strongpass123",
            },
            format="json",
        )
        user = User.objects.get(email="new@example.com")
        otp = OTPCode.objects.filter(
            user=user, purpose=OTPCode.Purpose.EMAIL_VERIFICATION
        ).latest("created_at")

        verify = self.client.post(
            "/api/auth/verify/",
            {"email": "new@example.com", "otp": otp.code},
            format="json",
        )
        self.assertEqual(verify.status_code, status.HTTP_200_OK)

        user.refresh_from_db()
        self.assertTrue(user.is_active)

        login = self.client.post(
            "/api/auth/login/",
            {"email": "new@example.com", "password": "strongpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertIn("access", login.data)
