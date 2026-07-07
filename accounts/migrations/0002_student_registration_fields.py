from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="contact_number",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="user",
            name="current_school",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="user",
            name="parent_full_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="user",
            name="parent_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="user",
            name="parent_contact_number",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="user",
            name="student_class",
            field=models.CharField(
                blank=True,
                max_length=8,
                choices=[
                    ("4th", "4th Form"),
                    ("5th", "5th Form"),
                    ("6th", "6th Form"),
                    ("7th", "7th Form"),
                    ("8th", "8th Form"),
                    ("9th", "9th Form"),
                    ("10th", "10th Form"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="preferred_time",
            field=models.CharField(
                blank=True,
                max_length=16,
                choices=[
                    ("morning", "Morning 12:00 Am-02:00PM"),
                    ("afternoon", "Afternoon 10:00 Am-12:00PM"),
                    ("evening", "Evening 12:00 Am-02:00PM"),
                ],
            ),
        ),
    ]