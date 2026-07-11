from rest_framework import serializers

from .models import Attempt, AttemptAnswer
from quizzes.models import Quiz

class SubmitAnswerSerializer(serializers.Serializer):
    question = serializers.IntegerField(help_text="Question id")
    selected_option = serializers.IntegerField(
        required=False, allow_null=True, help_text="1-based option index; null to skip"
    )


class SubmitQuizSerializer(serializers.Serializer):
    answers = SubmitAnswerSerializer(many=True)

    def validate_answers(self, value):
        if not value:
            raise serializers.ValidationError("At least one answer is required.")
        return value


class AttemptAnswerResultSerializer(serializers.ModelSerializer):
    question_no = serializers.IntegerField(source="question.question_no")
    question_text = serializers.CharField(source="question.question_text")
    options = serializers.JSONField(source="question.options")
    correct_answer = serializers.IntegerField(source="question.correct_answer")
    steps = serializers.JSONField(source="question.steps")

    class Meta:
        model = AttemptAnswer
        fields = [
            "question",
            "question_no",
            "question_text",
            "options",
            "selected_option",
            "correct_answer",
            "is_correct",
            "steps",
        ]


class AttemptResultSerializer(serializers.ModelSerializer):
    """Detailed result including correct answers + step-by-step solutions."""

    percentage = serializers.FloatField(read_only=True)
    accuracy = serializers.FloatField(source="percentage", read_only=True)
    quiz_title = serializers.CharField(source="quiz.title", read_only=True)
    reference_pdf_url = serializers.SerializerMethodField()
    answers = AttemptAnswerResultSerializer(many=True, read_only=True)

    class Meta:
        model = Attempt
        fields = [
            "id",
            "quiz",
            "quiz_title",
            "reference_pdf_url",
            "score",
            "total",
            "percentage",
            "accuracy",
            "submitted_at",
            "answers",
        ]

    def get_reference_pdf_url(self, obj):
        """Return the full absolute URL for the quiz's reference PDF, or None."""
        pdf = obj.quiz.reference_pdf
        if not pdf:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(pdf.url)
        from django.conf import settings
        base = getattr(settings, "BACKEND_URL", "").rstrip("/")
        return f"{base}{pdf.url}"


class MyAttemptSerializer(serializers.ModelSerializer):
    """Compact summary for a student's list of past quizzes."""

    percentage = serializers.FloatField(read_only=True)
    quiz_title = serializers.CharField(source="quiz.title", read_only=True)

    class Meta:
        model = Attempt
        fields = [
            "id",
            "quiz",
            "quiz_title",
            "score",
            "total",
            "percentage",
            "submitted_at",
        ]


class LeaderboardEntrySerializer(serializers.ModelSerializer):
    rank = serializers.IntegerField(read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    percentage = serializers.FloatField(read_only=True)

    class Meta:
        model = Attempt
        fields = [
            "rank",
            "student_name",
            "score",
            "total",
            "percentage",
            "submitted_at",
        ]


class TopStudentSerializer(serializers.Serializer):
    """A single row in the dashboard "Top Students" table."""

    student_id = serializers.IntegerField(read_only=True)
    student_name = serializers.CharField(read_only=True)
    average_score = serializers.FloatField(read_only=True)
    quizzes_completed = serializers.IntegerField(read_only=True)


class RecentQuizUploadSerializer(serializers.ModelSerializer):
    """A single row in the dashboard "Recent Quiz uploads" table."""

    # Real number of generated questions (annotated in the view for efficiency).
    questions = serializers.IntegerField(source="questions_total", read_only=True)
    # Maps is_published -> "Published" / "Draft" to match the dashboard column.
    status = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "questions",
            "status",
            "is_published",
            "created_at",
        ]

    def get_status(self, obj):
        return "Published" if obj.is_published else "Draft"