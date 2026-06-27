from rest_framework import serializers

from .models import Question, Quiz


class QuestionSerializer(serializers.ModelSerializer):
    """Full question representation (admin view / editing)."""

    class Meta:
        model = Question
        fields = [
            "id",
            "quiz",
            "question_no",
            "question_text",
            "options",
            "correct_answer",
            "steps",
            "chapter",
            "topic",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        options = attrs.get("options", getattr(self.instance, "options", None))
        correct = attrs.get(
            "correct_answer", getattr(self.instance, "correct_answer", None)
        )
        if options is not None:
            if not isinstance(options, list) or len(options) < 2:
                raise serializers.ValidationError(
                    {"options": "Provide at least two options."}
                )
            if correct is not None and not (1 <= correct <= len(options)):
                raise serializers.ValidationError(
                    {
                        "correct_answer": (
                            "correct_answer must be a 1-based index within options."
                        )
                    }
                )
        return attrs


class QuestionTakeSerializer(serializers.ModelSerializer):
    """Question as seen by a student taking the quiz (no answer/solution)."""

    class Meta:
        model = Question
        fields = ["id", "question_no", "question_text", "options"]


class QuizListSerializer(serializers.ModelSerializer):
    question_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "book_name",
            "chapter",
            "topic",
            "num_questions",
            "question_count",
            "status",
            "is_published",
            "created_at",
        ]


class QuizSerializer(serializers.ModelSerializer):
    """Full quiz with questions (admin retrieve)."""

    questions = QuestionSerializer(many=True, read_only=True)
    question_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "book_name",
            "chapter",
            "topic",
            "num_questions",
            "reference_pdf",
            "question_count",
            "status",
            "generation_error",
            "is_published",
            "created_by",
            "created_at",
            "updated_at",
            "questions",
        ]
        read_only_fields = [
            "status",
            "generation_error",
            "created_by",
            "created_at",
            "updated_at",
        ]


class QuizCreateSerializer(serializers.ModelSerializer):
    """Admin creates a quiz; generation is kicked off via Celery in the view."""

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "book_name",
            "chapter",
            "topic",
            "num_questions",
            "reference_pdf",
            "is_published",
        ]

    def validate_num_questions(self, value):
        if value < 1 or value > 50:
            raise serializers.ValidationError("num_questions must be between 1 and 50.")
        return value

class QuizRegenerateSerializer(serializers.ModelSerializer):
    """Optional edits applied before re-running AI generation.

    Every field is optional, so the admin can tweak just the question count,
    the topic, the chapter, etc. before regenerating.
    """

    class Meta:
        model = Quiz
        fields = [
            "title",
            "description",
            "book_name",
            "chapter",
            "topic",
            "num_questions",
            "reference_pdf",
            "is_published",
        ]
        extra_kwargs = {field: {"required": False} for field in fields}
    def validate_num_questions(self, value):
        if value < 1 or value > 50:
            raise serializers.ValidationError("num_questions must be between 1 and 50.")
        return value

class QuizTakeSerializer(serializers.ModelSerializer):
    """Quiz as seen by a student about to take it (answers hidden)."""

    questions = QuestionTakeSerializer(many=True, read_only=True)

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "book_name",
            "chapter",
            "topic",
            "num_questions",
            "questions",
        ]

class QuizStatusSerializer(serializers.ModelSerializer):
    """Lightweight payload for the frontend to poll generation progress."""

    generated = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = [
            "id",
            "status",
            "generation_error",
            "task_id",
            "num_questions",
            "generated",
            "progress",
        ]

    def get_generated(self, obj):
        return obj.questions.count()

    def get_progress(self, obj):
        if not obj.num_questions:
            return 0
        ratio = min(obj.questions.count() / obj.num_questions, 1)
        return round(ratio * 100, 1)