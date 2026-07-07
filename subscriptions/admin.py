from django.contrib import admin

from .models import Payment, Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "plan", "status", "current_period_end", "updated_at"]
    list_filter = ["plan", "status"]
    search_fields = ["user__email"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "order_id", "user", "amount", "currency", "status",
        "dimepay_transaction_id", "created_at",
    ]
    list_filter = ["status", "currency"]
    search_fields = ["order_id", "user__email", "dimepay_transaction_id"]