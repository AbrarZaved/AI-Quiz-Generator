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

    def test_default_free_subscription_and_tokens_on_signup_verify_and_login(self):
        from subscriptions.models import Subscription
        import jwt

        # 1. Test Signup
        res = self.client.post(
            "/api/auth/signup/",
            {
                "email": "test_flags@example.com",
                "full_name": "Test Flags User",
                "password": "strongpass123",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        
        # Verify default subscription was created
        user = User.objects.get(email="test_flags@example.com")
        sub = Subscription.objects.get(user=user)
        self.assertEqual(sub.plan, "free_trial")
        self.assertEqual(sub.status, "trialing")
        
        # Verify tokens and flags in signup response
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        self.assertEqual(res.data["plan"], "free_trial")
        self.assertEqual(res.data["is_premium"], False)
        self.assertEqual(res.data["is_free"], True)
        self.assertEqual(res.data["user"]["email"], "test_flags@example.com")
        self.assertEqual(res.data["user"]["plan"], "free_trial")
        self.assertEqual(res.data["user"]["is_premium"], False)
        self.assertEqual(res.data["user"]["is_free"], True)

        # 2. Test Verification
        otp = OTPCode.objects.filter(
            user=user, purpose=OTPCode.Purpose.EMAIL_VERIFICATION
        ).latest("created_at")

        verify = self.client.post(
            "/api/auth/verify/",
            {"email": "test_flags@example.com", "otp": otp.code},
            format="json",
        )
        self.assertEqual(verify.status_code, status.HTTP_200_OK)
        
        # Verify tokens and flags in verification response
        self.assertIn("access", verify.data)
        self.assertIn("refresh", verify.data)
        self.assertEqual(verify.data["plan"], "free_trial")
        self.assertEqual(verify.data["is_premium"], False)
        self.assertEqual(verify.data["is_free"], True)
        self.assertEqual(verify.data["user"]["plan"], "free_trial")
        
        # 3. Test Login
        login = self.client.post(
            "/api/auth/login/",
            {"email": "test_flags@example.com", "password": "strongpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        
        # Verify tokens and flags in login response
        self.assertIn("access", login.data)
        self.assertIn("refresh", login.data)
        self.assertEqual(login.data["plan"], "free_trial")
        self.assertEqual(login.data["is_premium"], False)
        self.assertEqual(login.data["is_free"], True)
        self.assertEqual(login.data["user"]["plan"], "free_trial")
        
        # Verify JWT payload contains the flags
        access_token = login.data["access"]
        payload = jwt.decode(access_token, options={"verify_signature": False})
        self.assertEqual(payload["plan"], "free_trial")
        self.assertEqual(payload["is_premium"], False)
        self.assertEqual(payload["is_free"], True)

