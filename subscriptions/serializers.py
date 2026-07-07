from rest_framework import serializers

from .models import Payment, Subscription, SubscriptionPlan

class SubscriptionSerializer(serializers.ModelSerializer):
    is_premium = serializers.BooleanField(read_only=True)

    class Meta:
        model = Subscription
        fields = ["plan", "status", "current_period_end", "is_premium", "updated_at"]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["order_id", "amount", "currency", "status", "order_url", "created_at"]
        read_only_fields = fields


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """Read + admin-edit serializer for a plan.

    `code` is read-only so admins edit price/name/etc. without remapping the
    plan to a different enum value.
    """

    code_display = serializers.CharField(source="get_code_display", read_only=True)

    class Meta:
        model = SubscriptionPlan
        fields = [
            "id",
            "code",
            "code_display",
            "name",
            "description",
            "price",
            "currency",
            "billing_period_days",
            "is_active",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "code_display", "updated_at"]