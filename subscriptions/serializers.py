from rest_framework import serializers

from .models import Payment, Subscription


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