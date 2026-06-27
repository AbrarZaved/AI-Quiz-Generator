from rest_framework import serializers

from .models import Attempt, AttemptAnswer


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
    steps = serializers.CharField(source="question.steps")

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
    quiz_title = serializers.CharField(source="quiz.title", read_only=True)
    answers = AttemptAnswerResultSerializer(many=True, read_only=True)

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
            "answers",
        ]


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
