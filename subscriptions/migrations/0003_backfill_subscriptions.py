from django.db import migrations


def backfill_subscriptions(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Subscription = apps.get_model("subscriptions", "Subscription")

    for user in User.objects.all():
        if not Subscription.objects.filter(user=user).exists():
            Subscription.objects.create(
                user=user,
                plan="free_trial",
                status="trialing",
            )


def reverse_backfill_subscriptions(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0002_subscriptionplan"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_subscriptions, reverse_backfill_subscriptions),
    ]
