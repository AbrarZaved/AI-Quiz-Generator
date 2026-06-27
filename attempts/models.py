from django.conf import settings
from django.db import models

from quizzes.models import Question, Quiz


class Attempt(models.Model):
    """A student's single attempt at a quiz (one attempt per student/quiz)."""

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE, related_name="attempts"
    )
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-score", "submitted_at"]
        unique_together = ("student", "quiz")

    def __str__(self):
        return f"{self.student.email} - {self.quiz.title} ({self.score}/{self.total})"

    @property
    def percentage(self):
        if not self.total:
            return 0.0
        return round((self.score / self.total) * 100, 2)


class AttemptAnswer(models.Model):
    """A single answer within an attempt."""

    attempt = models.ForeignKey(
        Attempt, on_delete=models.CASCADE, related_name="answers"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="attempt_answers"
    )
    # 1-based index the student selected (null = skipped).
    selected_option = models.PositiveSmallIntegerField(null=True, blank=True)
    is_correct = models.BooleanField(default=False)

    class Meta:
        unique_together = ("attempt", "question")

    def __str__(self):
        return f"{self.attempt_id} - Q{self.question.question_no}"
