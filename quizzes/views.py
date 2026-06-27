from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Question, Quiz
from .permissions import IsAdminRole
from .serializers import (
    QuestionSerializer,
    QuizCreateSerializer,
    QuizListSerializer,
    QuizRegenerateSerializer,
    QuizSerializer,
    QuizStatusSerializer,
    QuizTakeSerializer,
)
from .tasks import generate_quiz_task


class QuizViewSet(viewsets.ModelViewSet):
    """Admins: full CRUD + generate. Students: list/retrieve published quizzes."""

    def get_queryset(self):
        user = self.request.user
        qs = Quiz.objects.all().prefetch_related("questions")
        if user.is_authenticated and user.is_admin:
            return qs
        # Students only see published + ready quizzes.
        return qs.filter(is_published=True, status=Quiz.Status.READY)

    def get_permissions(self):
        if self.action in ("list", "retrieve", "take"):
            return [IsAuthenticated()]
        return [IsAdminRole()]

    def get_serializer_class(self):
        if self.action == "create":
            return QuizCreateSerializer
        if self.action == "list":
            return QuizListSerializer
        if self.action == "take":
            return QuizTakeSerializer
        # retrieve / update
        user = self.request.user
        if user.is_authenticated and user.is_admin:
            return QuizSerializer
        return QuizTakeSerializer

    def perform_create(self, serializer):
        # Creating a quiz auto-starts AI generation in the background.
        quiz = serializer.save(
            created_by=self.request.user, status=Quiz.Status.PENDING
        )
        result = generate_quiz_task.delay(quiz.id)
        quiz.task_id = result.id
        quiz.save(update_fields=["task_id"])

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        quiz = Quiz.objects.get(pk=serializer.instance.pk)
        return Response(
            QuizSerializer(quiz, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def take(self, request, pk=None):
        """Student-facing view of a quiz (no correct answers / solutions)."""
        quiz = self.get_object()
        serializer = QuizTakeSerializer(quiz, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        """Admin regenerates a quiz, optionally changing its parameters first.

        Accepts any of: title, description, book_name, chapter, topic,
        num_questions, is_published (all optional). The quiz is updated, its
        old questions are cleared by the task, and a fresh Celery generation
        run is queued. Poll GET /quizzes/{id}/status/ for progress.
        """
        quiz = self.get_object()
        if quiz.status == Quiz.Status.GENERATING:
            return Response(
                QuizStatusSerializer(quiz).data,
                status=status.HTTP_409_CONFLICT,
            )

        # Apply any edits the admin sent (question count, topic, chapter, etc.).
        serializer = QuizRegenerateSerializer(quiz, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        quiz.refresh_from_db()
        quiz.status = Quiz.Status.PENDING
        quiz.generation_error = ""
        quiz.save(update_fields=["status", "generation_error"])

        result = generate_quiz_task.delay(quiz.id)
        quiz.task_id = result.id
        quiz.save(update_fields=["task_id"])
        quiz.refresh_from_db()

        return Response(
            QuizSerializer(quiz, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        """Poll generation status/progress for a quiz."""
        quiz = self.get_object()
        return Response(QuizStatusSerializer(quiz).data)


class QuestionViewSet(viewsets.ModelViewSet):
    """Admin-only CRUD on individual questions (edit answer/options/delete)."""

    queryset = Question.objects.select_related("quiz").all()
    serializer_class = QuestionSerializer
    permission_classes = [IsAdminRole]

    def get_queryset(self):
        qs = super().get_queryset()
        quiz_id = self.request.query_params.get("quiz")
        if quiz_id:
            qs = qs.filter(quiz_id=quiz_id)
        return qs
