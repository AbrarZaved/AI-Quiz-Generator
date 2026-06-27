import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STUDENT = "student", "Student"

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.STUDENT
    )

    # New signups start inactive until their email OTP is verified.
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT


class OTPCode(models.Model):
    """One-time codes for email verification (signup) and password reset."""

    class Purpose(models.TextChoices):
        EMAIL_VERIFICATION = "email_verification", "Email verification"
        PASSWORD_RESET = "password_reset", "Password reset"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="otp_codes",
    )
    purpose = models.CharField(
        max_length=32,
        choices=Purpose.choices,
        default=Purpose.EMAIL_VERIFICATION,
    )
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        state = "used" if self.is_used else "active"
        return f"{self.get_purpose_display()} OTP for {self.user.email} ({state})"

    @property
    def is_valid(self):
        return (not self.is_used) and timezone.now() < self.expires_at

    @classmethod
    def generate_for(cls, user, purpose):
        # Invalidate any previously issued, still-active codes for this purpose.
        cls.objects.filter(user=user, purpose=purpose, is_used=False).update(
            is_used=True
        )
        code = f"{random.randint(0, 999999):06d}"
        expires_at = timezone.now() + timedelta(
            minutes=settings.OTP_EXPIRY_MINUTES
        )
        return cls.objects.create(
            user=user, purpose=purpose, code=code, expires_at=expires_at
        )
