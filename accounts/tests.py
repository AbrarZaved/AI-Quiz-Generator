from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from django.test import override_settings
from accounts.models import OTPCode

User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
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
        from django.core.mail import outbox
        import re

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

        # Parse temporary password from outbox
        temp_pass_email = [email for email in outbox if "Your Temporary Password" in email.subject][0]
        match = re.search(r"log in to your account:\s+(\w+)", temp_pass_email.body)
        temp_password = match.group(1) if match else re.findall(r"\b[a-zA-Z0-9]{10}\b", temp_pass_email.body)[0]

        login = self.client.post(
            "/api/auth/login/",
            {"email": "new@example.com", "password": temp_password},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertIn("access", login.data)

    def test_default_free_subscription_and_tokens_on_signup_verify_and_login(self):
        from subscriptions.models import Subscription
        from django.core.mail import outbox
        import jwt
        import re

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
        
        # Verify tokens are NOT in signup response
        self.assertNotIn("access", res.data)
        self.assertNotIn("refresh", res.data)

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
        
        # Parse temporary password from outbox
        temp_pass_email = [email for email in outbox if "Your Temporary Password" in email.subject][0]
        match = re.search(r"log in to your account:\s+(\w+)", temp_pass_email.body)
        temp_password = match.group(1) if match else re.findall(r"\b[a-zA-Z0-9]{10}\b", temp_pass_email.body)[0]

        # 3. Test Login
        login = self.client.post(
            "/api/auth/login/",
            {"email": "test_flags@example.com", "password": temp_password},
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

    def test_public_endpoints_ignore_invalid_token(self):
        res = self.client.post(
            "/api/auth/register/",
            {
                "full_name": "Public Registration User",
                "email": "public_reg@example.com",
                "contact_number": "12345678",
                "current_school": "Test School",
                "parent_full_name": "Parent Name",
                "parent_email": "parent@example.com",
                "parent_contact_number": "87654321",
                "student_class": "4th",
                "preferred_time": "morning",
            },
            HTTP_AUTHORIZATION="Bearer invalid-expired-or-bad-token",
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ContactMessageTests(APITestCase):
    def test_contact_message_validation_error(self):
        # Missing fields should fail
        res = self.client.post("/api/auth/contact/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("full_name", res.data)
        self.assertIn("email", res.data)
        self.assertIn("subject", res.data)
        self.assertIn("message", res.data)

    def test_contact_message_success(self):
        from django.core.mail import outbox

        # Create active superusers
        User.objects.create_superuser(
            email="admin1@example.com",
            full_name="Admin One",
            password="adminpassword123",
        )
        User.objects.create_superuser(
            email="admin2@example.com",
            full_name="Admin Two",
            password="adminpassword123",
        )
        # Create student to ensure they are not included
        User.objects.create_user(
            email="student@example.com",
            full_name="Student",
            password="studentpassword123",
        )

        outbox.clear()

        res = self.client.post(
            "/api/auth/contact/",
            {
                "full_name": "John Doe",
                "email": "johndoe@example.com",
                "subject": "AI Quiz Generation",
                "message": "Hello, I have a question about AI quiz generation.",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["detail"], "Your message has been sent successfully.")

        # Check outbox
        self.assertEqual(len(outbox), 1)
        email = outbox[0]
        self.assertEqual(email.subject, "Contact Us Form Submission: AI Quiz Generation")
        self.assertIn("John Doe", email.body)
        self.assertIn("johndoe@example.com", email.body)
        self.assertIn("Hello, I have a question about AI quiz generation.", email.body)

        # Verify recipients are all active superusers
        self.assertEqual(set(email.to), {"admin1@example.com", "admin2@example.com"})

        # Verify reply_to matches the sender's email
        self.assertEqual(email.reply_to, ["johndoe@example.com"])



