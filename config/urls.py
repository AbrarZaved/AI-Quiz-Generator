from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from django.conf import settings
from django.conf.urls.static import static
urlpatterns = [
    path("admin/", admin.site.urls),
    # Auth (signup, login, token refresh, OTP password reset, me)
    path("api/auth/", include("accounts.urls")),
    # Quizzes + questions
    path("api/", include("quizzes.urls")),
    # Attempts, results, leaderboard
    path("api/", include("attempts.urls")),
    # OpenAPI schema + Swagger UI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    # Subscriptions + DimePay payments
    path("api/billing/", include("subscriptions.urls")),
]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)