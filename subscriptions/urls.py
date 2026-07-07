from django.urls import path

from .views import (
    CancelSubscriptionView,
    CreatePremiumCheckoutView,
    DimePayWebhookView,
    StartFreeTrialView,
    SubscriptionStatusView,
    SubscriptionPlanListView,
    AdminSubscriptionPlanDetailView,
)

urlpatterns = [
    path("subscription/", SubscriptionStatusView.as_view(), name="subscription-status"),
    path("free-trial/", StartFreeTrialView.as_view(), name="start-free-trial"),
    path("cancel/", CancelSubscriptionView.as_view(), name="cancel-subscription"),
    path("checkout/premium/", CreatePremiumCheckoutView.as_view(), name="premium-checkout"),
    path("webhook/dimepay/", DimePayWebhookView.as_view(), name="dimepay-webhook"),
    path("plans/", SubscriptionPlanListView.as_view(), name="subscription-plan-list"),
    path(
        "plans/<int:pk>/",
        AdminSubscriptionPlanDetailView.as_view(),
        name="subscription-plan-detail",
    ),
]