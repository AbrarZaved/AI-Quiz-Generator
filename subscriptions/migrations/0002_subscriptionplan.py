from decimal import Decimal

from django.db import migrations, models


def seed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    SubscriptionPlan.objects.get_or_create(
        code="free_trial",
        defaults={
            "name": "Free Trial",
            "price": Decimal("0.00"),
            "billing_period_days": 0,
        },
    )
    SubscriptionPlan.objects.get_or_create(
        code="premium",
        defaults={
            "name": "Premium",
            "price": Decimal("9.99"),
            "billing_period_days": 30,
        },
    )


def unseed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(
        code__in=["free_trial", "premium"]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionPlan",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        choices=[
                            ("free_trial", "Free Trial"),
                            ("premium", "Premium"),
                        ],
                        max_length=20,
                        unique=True,
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                (
                    "price",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=10,
                    ),
                ),
                ("currency", models.CharField(default="USD", max_length=8)),
                (
                    "billing_period_days",
                    models.PositiveIntegerField(default=30),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["price"]},
        ),
        migrations.RunPython(seed_plans, unseed_plans),
    ]