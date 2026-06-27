from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from .tasks import send_otp_email_task
from .models import OTPCode
from .serializers import (
    EmailTokenObtainPairSerializer,
    ForgotPasswordSerializer,
    ResendOTPSerializer,
    ResetPasswordSerializer,
    SignupSerializer,
    UserSerializer,
    VerifyAccountSerializer,
)

User = get_user_model()


def _send_otp_email(user, otp):
    """Send the OTP email for either verification or password reset."""
    if otp.purpose == OTPCode.Purpose.EMAIL_VERIFICATION:
        subject = "Verify your account"
        intro = "Use this code to verify your account and activate your login"
    else:
        subject = "Your password reset code"
        intro = "Use this code to reset your password"

    send_mail(
        subject=subject,
        message=(
            f"Hello {user.full_name},\n\n"
            f"{intro}: {otp.code}\n"
            f"It expires in {settings.OTP_EXPIRY_MINUTES} minutes.\n\n"
            "If you did not request this, you can ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


class SignupView(generics.CreateAPIView):
    """POST email, full_name, password -> create an inactive student and email an OTP."""

    permission_classes = [AllowAny]
    serializer_class = SignupSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        otp = OTPCode.generate_for(user, OTPCode.Purpose.EMAIL_VERIFICATION)
        send_otp_email_task.delay(user.id, otp.code, otp.purpose)

        return Response(
            {
                "detail": (
                    "Account created. We've emailed you a 6-digit code to verify "
                    "your account. Verify it to activate your login."
                ),
                "email": user.email,
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyAccountView(APIView):
    """POST email, otp -> activate the account so the user can log in."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = User.objects.filter(email__iexact=data["email"]).first()
        if user is None:
            return Response(
                {"detail": "Invalid OTP or email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user.is_active:
            return Response(
                {"detail": "Account is already verified. You can log in."},
                status=status.HTTP_200_OK,
            )

        otp = (
            OTPCode.objects.filter(
                user=user,
                code=data["otp"],
                purpose=OTPCode.Purpose.EMAIL_VERIFICATION,
            )
            .order_by("-created_at")
            .first()
        )
        if otp is None or not otp.is_valid:
            return Response(
                {"detail": "Invalid or expired OTP."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.is_active = True
        user.save(update_fields=["is_active"])
        otp.is_used = True
        otp.save(update_fields=["is_used"])

        return Response(
            {"detail": "Account verified and activated. You can now log in."},
            status=status.HTTP_200_OK,
        )


class ResendVerificationOTPView(APIView):
    """POST email -> resend the signup verification OTP (if account is unverified)."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        user = User.objects.filter(email__iexact=email).first()
        if user is not None and not user.is_active:
            otp = OTPCode.generate_for(user, OTPCode.Purpose.EMAIL_VERIFICATION)
            send_otp_email_task.delay(user.id, otp.code, otp.purpose)
        # Uniform response to avoid leaking which emails exist / are verified.
        return Response(
            {"detail": "If the account exists and is unverified, a new OTP has been sent."},
            status=status.HTTP_200_OK,
        )


class LoginView(TokenObtainPairView):
    """POST email, password -> { access, refresh, user }. Inactive accounts are rejected."""

    permission_classes = [AllowAny]
    serializer_class = EmailTokenObtainPairSerializer


class MeView(generics.RetrieveAPIView):
    """GET the currently authenticated user."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class ForgotPasswordView(APIView):
    """POST email -> emails a 6-digit OTP if the account exists."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            otp = OTPCode.generate_for(user, OTPCode.Purpose.PASSWORD_RESET)
            send_otp_email_task.delay(user.id, otp.code, otp.purpose)

        # Always return the same response so we don't leak which emails exist.
        return Response(
            {"detail": "If an account exists for that email, an OTP has been sent."},
            status=status.HTTP_200_OK,
        )


class ResetPasswordView(APIView):
    """POST email, otp, new_password -> sets a new password."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = User.objects.filter(email__iexact=data["email"]).first()
        if user is None:
            return Response(
                {"detail": "Invalid OTP or email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp = (
            OTPCode.objects.filter(
                user=user,
                code=data["otp"],
                purpose=OTPCode.Purpose.PASSWORD_RESET,
            )
            .order_by("-created_at")
            .first()
        )
        if otp is None or not otp.is_valid:
            return Response(
                {"detail": "Invalid or expired OTP."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(data["new_password"])
        user.save(update_fields=["password"])

        otp.is_used = True
        otp.save(update_fields=["is_used"])

        return Response(
            {"detail": "Password has been reset. You can now log in."},
            status=status.HTTP_200_OK,
        )
