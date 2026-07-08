from django.conf import settings
from django.db import models

from django.core.validators import FileExtensionValidator
class Quiz(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # AI generation parameters (fed to pipeline.py)
    book_name = models.CharField(max_length=100, help_text="e.g. volume1 / volume2")
    chapter = models.CharField(max_length=255)
    topic = models.CharField(max_length=255)
    num_questions = models.PositiveIntegerField(default=5)
    time_limit = models.PositiveIntegerField(
        default=30, help_text="Time limit for the quiz in minutes."
    )

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    generation_error = models.TextField(blank=True)
    is_published = models.BooleanField(
        default=False, help_text="Students only see published + ready quizzes."
    )
    task_id = models.CharField(max_length=255, blank=True)
    reference_pdf = models.FileField(
        upload_to="quiz_reference_pdfs/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["pdf"])],
        help_text="Optional PDF of previous questions, for reference.",
    )
    is_published = models.BooleanField(
        default=False, help_text="Students only see published + ready quizzes."
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_quizzes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Quizzes"

    def __str__(self):
        return self.title

    @property
    def question_count(self):
        return self.questions.count()


class Question(models.Model):
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE, related_name="questions"
    )
    question_no = models.PositiveIntegerField()
    question_text = models.TextField()
    # List of option strings, e.g. ["x = -1", "x = 6", ...]
    options = models.JSONField(default=list)
    # 1-based index of the correct option (matches pipeline.py output).
    correct_answer = models.PositiveSmallIntegerField()
    steps = models.JSONField(default=list, blank=True)

    chapter = models.CharField(max_length=255, blank=True)
    topic = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["question_no", "id"]
        unique_together = ("quiz", "question_no")

    def __str__(self):
        return f"Q{self.question_no} - {self.quiz.title}"
