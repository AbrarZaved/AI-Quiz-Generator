from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Plan(models.TextChoices):
    FREE_TRIAL = "free_trial", "Free Trial"
    PREMIUM = "premium", "Premium"


class Subscription(models.Model):
    class Status(models.TextChoices):
        INACTIVE = "inactive", "Inactive"
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELED = "canceled", "Canceled"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.CharField(
        max_length=20, choices=Plan.choices, default=Plan.FREE_TRIAL
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.INACTIVE
    )
    current_period_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.get_plan_display()} ({self.get_status_display()})"

    @property
    def is_premium(self):
        if self.plan != Plan.PREMIUM:
            return False
        if self.status != self.Status.ACTIVE:
            return False
        if self.current_period_end is None:
            return True
        return timezone.now() < self.current_period_end

    def activate_premium(self, days=30):
        self.plan = Plan.PREMIUM
        self.status = self.Status.ACTIVE
        self.current_period_end = timezone.now() + timedelta(days=days)
        self.save()

    def cancel_subscription(self):
        """Cancel the subscription.

        Sets status to CANCELED and downgrades the plan to FREE_TRIAL.
        ``current_period_end`` is preserved so the user retains access until
        the period expires (cancel-at-period-end semantics).
        """
        self.status = self.Status.CANCELED
        self.plan = Plan.FREE_TRIAL
        self.save(update_fields=["status", "plan", "updated_at"])


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    order_id = models.CharField(max_length=64, unique=True)
    dimepay_transaction_id = models.CharField(max_length=128, blank=True)
    order_url = models.URLField(blank=True)
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("9.99")
    )
    currency = models.CharField(max_length=8, default="USD")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order_id} - {self.user.email} - {self.get_status_display()}"


class SubscriptionPlan(models.Model):
    """Editable catalog entry for a subscription plan (name + price).

    `code` maps to the Plan enum value used elsewhere (free_trial / premium),
    so existing logic keeps working while the price becomes DB-editable.
    """

    code = models.CharField(
        max_length=20,
        choices=Plan.choices,
        unique=True,
        help_text="Maps to the Plan enum value (free_trial / premium).",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    currency = models.CharField(max_length=8, default="USD")
    billing_period_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["price"]

    def __str__(self):
        return f"{self.name} ({self.price} {self.currency})"


from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_subscription(sender, instance, created, **kwargs):
    if created:
        Subscription.objects.get_or_create(
            user=instance,
            defaults={
                "plan": Plan.FREE_TRIAL,
                "status": Subscription.Status.TRIALING,
            },
        )