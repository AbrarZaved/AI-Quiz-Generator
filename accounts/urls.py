from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ForgotPasswordView,
    LoginView,
    MeView,
    ResendVerificationOTPView,
    ResetPasswordView,
    SignupView,
    VerifyAccountView,
)

urlpatterns = [
    path("signup/", SignupView.as_view(), name="signup"),
    path("verify/", VerifyAccountView.as_view(), name="verify-account"),
    path("verify/resend/", ResendVerificationOTPView.as_view(), name="verify-resend"),
    path("login/", LoginView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("password/forgot/", ForgotPasswordView.as_view(), name="password-forgot"),
    path("password/reset/", ResetPasswordView.as_view(), name="password-reset"),
    path("me/", MeView.as_view(), name="me"),
]
