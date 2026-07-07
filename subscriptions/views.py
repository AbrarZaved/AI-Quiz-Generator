from locale import currency
import uuid
from decimal import Decimal

import jwt
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quizzes.permissions import IsAdminOrReadOnly
from .dimepay import DimePayClient, DimePayError
from .models import Payment, Plan, Subscription, SubscriptionPlan
from .serializers import SubscriptionPlanSerializer, SubscriptionSerializer

def _get_or_create_subscription(user):
    sub, _ = Subscription.objects.get_or_create(user=user)
    return sub


@extend_schema(
    tags=["Billing"],
    summary="Get the current user's subscription status",
)
class SubscriptionStatusView(APIView):
    """GET the current user's subscription state."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        sub = _get_or_create_subscription(request.user)
        return Response(SubscriptionSerializer(sub).data)


@extend_schema(
    tags=["Billing"],
    summary="Activate the Free Trial plan for the current user",
)
class StartFreeTrialView(APIView):
    """POST -> put the user on the Free Trial plan (no payment)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        sub = _get_or_create_subscription(request.user)
        sub.plan = Plan.FREE_TRIAL
        sub.status = Subscription.Status.TRIALING
        sub.current_period_end = None
        sub.save()
        return Response(SubscriptionSerializer(sub).data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Billing"],
    summary="Cancel the current user's active subscription",
)
class CancelSubscriptionView(APIView):
    """POST -> cancel the authenticated user's subscription.

    Only active or trialing subscriptions can be cancelled.  Attempting to
    cancel an already-cancelled or inactive subscription returns 400.
    The ``current_period_end`` is kept intact; the user retains access until
    that date, after which the free-tier limit applies.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        sub = _get_or_create_subscription(request.user)

        cancelable = {Subscription.Status.ACTIVE, Subscription.Status.TRIALING}
        if sub.status not in cancelable:
            return Response(
                {"detail": "No active subscription to cancel."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sub.cancel_subscription()
        return Response(SubscriptionSerializer(sub).data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Billing"],
    summary="Create a DimePay hosted checkout page for the Premium plan",
)
class CreatePremiumCheckoutView(APIView):
    """POST -> create a DimePay hosted checkout page; returns { order_id, order_url }."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        # Pull live pricing from the editable SubscriptionPlan catalog,
        # falling back to the settings value if the row is missing.
        premium_plan = SubscriptionPlan.objects.filter(
            code=Plan.PREMIUM, is_active=True
        ).first()
        if premium_plan is not None:
            amount = premium_plan.price
            currency = premium_plan.currency
        else:
            amount = Decimal(str(settings.PREMIUM_PRICE_USD))
            currency = "USD"

        order_id = f"SUB-{uuid.uuid4().hex[:12].upper()}"

        payment = Payment.objects.create(
            user=user,
            order_id=order_id,
            amount=amount,
            currency=currency,
            status=Payment.Status.PENDING,
        )

        client = DimePayClient()
        try:
            result = client.create_hosted_page(
                order_id=order_id,
                amount=amount,
                email=user.email,
                item_name="Excellim Premium (Monthly)",
                item_description="Unlimited access to all topics & quizzes",
                currency=currency,
            )
        except DimePayError as exc:
            payment.status = Payment.Status.FAILED
            payment.raw_response = {"error": str(exc)}
            payment.save()
            return Response(
                {"detail": "Could not start payment. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        order_url = result.get("order_url", "")
        payment.order_url = order_url
        payment.raw_response = result
        payment.save()

        return Response(
            {"order_id": order_id, "order_url": order_url},
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Billing"],
    summary="[DimePay webhook] Receive payment events and activate premium on success",
    exclude=True,  # Hide from public Swagger docs; internal webhook only.
)
class DimePayWebhookView(APIView):
    """DimePay -> backend payment events. Activates premium on success."""

    permission_classes = [AllowAny]
    authentication_classes = []

    SUCCESS_STATUSES = {"COMPLETE", "COMPLETED", "SETTLED", "CAPTURED", "PAID"}
    FAILED_STATUSES = {"FAILED", "DECLINED", "VOID", "VOIDED", "CANCELLED", "CANCELED"}

    def post(self, request):
        event = request.data or {}

        # DimePay may wrap the event as a signed JWT: {"lang": "en", "data": "<jwt>"}.
        if isinstance(event, dict) and isinstance(event.get("data"), str):
            try:
                event = jwt.decode(
                    event["data"],
                    settings.DIMEPAY_SIGNING_SECRET,
                    algorithms=["HS256"],
                )
            except jwt.PyJWTError:
                return Response(
                    {"detail": "Invalid signature."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        order_id = (
            event.get("entity_display_id")
            or event.get("referenceTransactionId")
            or event.get("id")
        )
        payment = (
            Payment.objects.filter(order_id=order_id).select_related("user").first()
        )
        if payment is None:
            # Acknowledge unknown orders so DimePay stops retrying.
            return Response({"received": True}, status=status.HTTP_200_OK)

        pay_status = str(event.get("status", "")).upper()
        payment.dimepay_transaction_id = (
            event.get("id")
            or event.get("external_transaction_id")
            or payment.dimepay_transaction_id
        )
        payment.raw_response = event

        if pay_status in self.SUCCESS_STATUSES or event.get("settled") is True:
            payment.status = Payment.Status.COMPLETE
            sub = _get_or_create_subscription(payment.user)
            sub.activate_premium(days=30)
            payment.subscription = sub
        elif event.get("refunded") is True or pay_status == "REFUNDED":
            payment.status = Payment.Status.REFUNDED
        elif pay_status in self.FAILED_STATUSES:
            payment.status = Payment.Status.FAILED

        payment.save()
        return Response({"received": True}, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Admin - Plans"],
    summary="List all subscription plans (public read for the pricing screen)",
)
class SubscriptionPlanListView(generics.ListAPIView):
    """GET every plan. Reads are open; only admins can write (via detail view)."""

    permission_classes = [IsAdminOrReadOnly]
    serializer_class = SubscriptionPlanSerializer
    queryset = SubscriptionPlan.objects.all()


@extend_schema(
    tags=["Admin - Plans"],
    summary="[Admin] Retrieve or edit a subscription plan's price & details",
)
class AdminSubscriptionPlanDetailView(generics.RetrieveUpdateAPIView):
    """GET one plan; PATCH/PUT to edit price/name/currency/etc. (admin only)."""

    permission_classes = [IsAdminOrReadOnly]
    serializer_class = SubscriptionPlanSerializer
    queryset = SubscriptionPlan.objects.all()
    lookup_field = "pk"