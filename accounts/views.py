from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from .tasks import send_otp_email_task
from .models import OTPCode
from .serializers import (
    ChangePasswordSerializer,
    EmailTokenObtainPairSerializer,
    ForgotPasswordSerializer,
    ResendOTPSerializer,
    ResetPasswordSerializer,
    SignupSerializer,
    UpdateProfileSerializer,
    UserSerializer,
    VerifyAccountSerializer,
    AdminStudentListSerializer,
    AdminStudentDetailSerializer,
)
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.pagination import PageNumberPagination

from quizzes.permissions import IsAdminRole
from subscriptions.models import Plan, Subscription

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


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    refresh["full_name"] = user.full_name
    
    sub = getattr(user, "subscription", None)
    refresh["plan"] = sub.plan if sub else "free_trial"
    refresh["is_premium"] = bool(sub and sub.is_premium)
    refresh["is_free"] = not bool(sub and sub.is_premium)
    
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


@extend_schema(tags=["Auth"])
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

        tokens = get_tokens_for_user(user)
        sub = getattr(user, "subscription", None)
        return Response(
            {
                "detail": (
                    "Account created. We've emailed you a 6-digit code to verify "
                    "your account. Verify it to activate your login."
                ),
                "email": user.email,
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "plan": sub.plan if sub else "free_trial",
                "is_premium": bool(sub and sub.is_premium),
                "is_free": not bool(sub and sub.is_premium),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )

from .serializers import (  # add to the existing serializers import
    StudentRegistrationSerializer,
)


@extend_schema(tags=["Auth"])
class RegisterStudentView(generics.CreateAPIView):
    """POST the full 4-step registration payload -> create an inactive student and email an OTP."""

    permission_classes = [AllowAny]
    serializer_class = StudentRegistrationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        otp = OTPCode.generate_for(user, OTPCode.Purpose.EMAIL_VERIFICATION)
        send_otp_email_task.delay(user.id, otp.code, otp.purpose)

        tokens = get_tokens_for_user(user)
        sub = getattr(user, "subscription", None)
        return Response(
            {
                "detail": (
                    "Registration received. We've emailed a 6-digit code to "
                    "verify the account."
                ),
                "email": user.email,
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "plan": sub.plan if sub else "free_trial",
                "is_premium": bool(sub and sub.is_premium),
                "is_free": not bool(sub and sub.is_premium),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )

@extend_schema(tags=["Auth"])
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

        tokens = get_tokens_for_user(user)
        sub = getattr(user, "subscription", None)
        return Response(
            {
                "detail": "Account verified and activated. You can now log in.",
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "plan": sub.plan if sub else "free_trial",
                "is_premium": bool(sub and sub.is_premium),
                "is_free": not bool(sub and sub.is_premium),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Auth"])
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


@extend_schema(tags=["Auth"])
class LoginView(TokenObtainPairView):
    """POST email, password -> { access, refresh, user }. Inactive accounts are rejected."""

    permission_classes = [AllowAny]
    serializer_class = EmailTokenObtainPairSerializer


@extend_schema(tags=["Auth"])
class MeView(generics.RetrieveAPIView):
    """GET the currently authenticated user."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


@extend_schema(
    tags=["Auth"],
    summary="Update the current user's profile (partial update)",
    request=UpdateProfileSerializer,
    responses={200: UserSerializer},
)
class UpdateProfileView(APIView):
    """PATCH any subset of profile fields for the authenticated user.

    Email and role are immutable through this endpoint.
    Returns the full user object after the update.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request):
        serializer = UpdateProfileSerializer(
            instance=request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Auth"],
    summary="Change password for the currently authenticated user",
)
class ChangePasswordView(APIView):
    """POST old_password, new_password, confirm_password -> updates the password.

    Requires authentication. The old password is verified before the change
    is applied. Django's full password-validation suite runs on the new value.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response(
            {"detail": "Password changed successfully."},
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Auth"])
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


@extend_schema(tags=["Auth"])
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

class StudentTablePagination(PageNumberPagination):
    """10 rows per page (matches the dashboard) with client-tunable size."""

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data["total_pages"] = self.page.paginator.num_pages
        response.data["current_page"] = self.page.number
        return response


@extend_schema(
    tags=["Admin - Students"],
    summary="[Admin] List/search students with plan & status + summary counts",
)
class AdminStudentListView(generics.ListAPIView):
    """GET the admin Student table: paginated rows + the four summary counts.

    Supports ?search=, ?plan=, ?status=, ?class=, ?page=, ?page_size=.
    """

    permission_classes = [IsAdminRole]
    serializer_class = AdminStudentListSerializer
    pagination_class = StudentTablePagination

    # ------------------------------------------------------------------
    # Querysets
    # ------------------------------------------------------------------
    def _premium_subquery(self):
        """Correlated subquery: does this user have an ACTIVE premium plan?"""
        now = timezone.now()
        return Subscription.objects.filter(
            user_id=OuterRef("pk"),
            plan=Plan.PREMIUM,
            status=Subscription.Status.ACTIVE,
        ).filter(
            Q(current_period_end__isnull=True) | Q(current_period_end__gt=now)
        )

    def get_base_queryset(self):
        return User.objects.filter(role=User.Role.STUDENT).annotate(
            is_premium=Exists(self._premium_subquery())
        )

    def get_queryset(self):
        qs = self.get_base_queryset()
        params = self.request.query_params

        search = params.get("search")
        if search:
            qs = qs.filter(
                Q(full_name__icontains=search) | Q(email__icontains=search)
            )

        student_class = params.get("class") or params.get("student_class")
        if student_class:
            qs = qs.filter(student_class=student_class)

        plan = params.get("plan")
        if plan == "premium":
            qs = qs.filter(is_premium=True)
        elif plan in ("free", "free_trial"):
            qs = qs.filter(is_premium=False)

        status_param = params.get("status")
        if status_param == "active":
            qs = qs.filter(is_active=True)
        elif status_param == "inactive":
            qs = qs.filter(is_active=False)

        # Ascending Id to match the dashboard's row numbering.
        return qs.order_by("id")

    # ------------------------------------------------------------------
    # Summary cards (computed over ALL students, ignoring pagination)
    # ------------------------------------------------------------------
    def get_stats(self):
        base = self.get_base_queryset()
        total = base.count()
        premium = base.filter(is_premium=True).count()
        return {
            "total_students": total,
            "active_students": base.filter(is_active=True).count(),
            "premium_students": premium,
            "free_students": total - premium,
        }

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        # Attach the summary cards alongside the paginated results.
        response.data["stats"] = self.get_stats()
        return response
        
@extend_schema(
    tags=["Admin - Students"],
    summary="[Admin] Retrieve one student's full profile, subscription, payment & quiz history",
)
class AdminStudentDetailView(generics.RetrieveAPIView):
    """GET a single student's complete detail record (admin only)."""

    permission_classes = [IsAdminRole]
    serializer_class = AdminStudentDetailSerializer
    queryset = User.objects.filter(role=User.Role.STUDENT)
    lookup_field = "pk"