from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from subscriptions.permissions import FREE_TRIAL_QUIZ_LIMIT

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


@extend_schema_view(
    list=extend_schema(
        tags=["Quizzes"],
        summary="List all published quizzes (students) or all quizzes (admins)",
    ),
    retrieve=extend_schema(
        tags=["Quizzes"],
        summary="Retrieve a single quiz by ID",
    ),
    create=extend_schema(
        tags=["Quizzes"],
        summary="[Admin] Create a quiz and kick off AI generation",
    ),
    update=extend_schema(
        tags=["Quizzes"],
        summary="[Admin] Full update of a quiz",
    ),
    partial_update=extend_schema(
        tags=["Quizzes"],
        summary="[Admin] Partially update a quiz",
    ),
    destroy=extend_schema(
        tags=["Quizzes"],
        summary="[Admin] Delete a quiz",
    ),
)
class QuizViewSet(viewsets.ModelViewSet):
    """Admins: full CRUD + generate. Students: list/retrieve published quizzes.

    Free-tier students can see all quizzes in the list but may only open
    (retrieve / take) the first FREE_TRIAL_QUIZ_LIMIT quizzes (ordered by
    creation date, oldest first).  Premium students have no restriction.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_premium(self, user):
        """Return True when *user* has an active premium subscription."""
        sub = getattr(user, "subscription", None)
        return bool(sub and sub.is_premium)

    def _free_quiz_ids(self, student_qs):
        """IDs of the FREE_TRIAL_QUIZ_LIMIT oldest published+ready quizzes."""
        return list(
            student_qs.order_by("created_at").values_list("id", flat=True)[
                :FREE_TRIAL_QUIZ_LIMIT
            ]
        )

    def _require_access(self, quiz):
        """Raise PermissionDenied if a free user tries to open a locked quiz."""
        user = self.request.user
        if user.is_admin or self._is_premium(user):
            return
        student_qs = Quiz.objects.filter(is_published=True, status=Quiz.Status.READY)
        if quiz.id not in self._free_quiz_ids(student_qs):
            raise PermissionDenied(
                "A premium subscription is required to access this quiz."
            )

    # ------------------------------------------------------------------
    # Standard viewset overrides
    # ------------------------------------------------------------------

    def get_queryset(self):
        user = self.request.user
        qs = Quiz.objects.all().prefetch_related("questions")
        if user.is_authenticated and user.is_admin:
            published = self.request.query_params.get("published")
            if published is not None:
                qs = qs.filter(is_published=published.lower() == "true")
            return qs
        # Students (free & premium) see all published + ready quizzes so that
        # the frontend can render the full list with lock indicators.
        return qs.filter(is_published=True, status=Quiz.Status.READY)

    def get_serializer_context(self):
        """Inject free_quiz_ids so QuizListSerializer can mark locked quizzes."""
        ctx = super().get_serializer_context()
        user = self.request.user
        if user.is_authenticated and not user.is_admin and not self._is_premium(user):
            student_qs = Quiz.objects.filter(
                is_published=True, status=Quiz.Status.READY
            )
            ctx["free_quiz_ids"] = self._free_quiz_ids(student_qs)
        else:
            # None signals "no restriction" to the serializer.
            ctx["free_quiz_ids"] = None
        return ctx

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
        # Auto-start generation. is_published comes straight from the request
        # (defaults to False = draft when the admin doesn't send it).
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

    @extend_schema(tags=["Quizzes"], summary="Student view: open a quiz (answers hidden)")
    def retrieve(self, request, *args, **kwargs):
        quiz = self.get_object()
        self._require_access(quiz)
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(tags=["Quizzes"], summary="Student view: take a quiz (no correct answers returned)")
    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def take(self, request, pk=None):
        """Student-facing view of a quiz (no correct answers / solutions)."""
        quiz = self.get_object()
        self._require_access(quiz)
        serializer = QuizTakeSerializer(quiz, context=self.get_serializer_context())
        return Response(serializer.data)

    @extend_schema(tags=["Quizzes"], summary="[Admin] Regenerate questions for an existing quiz")
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

    @extend_schema(tags=["Quizzes"], summary="[Admin] Poll AI generation progress for a quiz")
    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        """Poll generation status/progress for a quiz."""
        quiz = self.get_object()
        return Response(QuizStatusSerializer(quiz).data)

    @extend_schema(
        tags=["Quizzes"],
        summary="[Admin] Quiz counts: total, published, and draft",
    )
    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Return aggregate quiz counts for the admin dashboard.

        Draft quizzes are those with ``is_published=False``.
        """
        all_qs = Quiz.objects.all()
        total = all_qs.count()
        published = all_qs.filter(is_published=True).count()
        draft = all_qs.filter(is_published=False).count()
        return Response(
            {"total": total, "published": published, "draft": draft},
            status=status.HTTP_200_OK,
        )

    @extend_schema(tags=["Quizzes"], summary="[Admin] Publish a ready quiz so students can see it")
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        """Publish a generated (ready) quiz so students can see it."""
        quiz = self.get_object()
        if quiz.status != Quiz.Status.READY:
            return Response(
                {"detail": "Only a fully generated (ready) quiz can be published."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        quiz.is_published = True
        quiz.save(update_fields=["is_published"])
        return Response(
            QuizSerializer(quiz, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(tags=["Quizzes"], summary="[Admin] Unpublish a quiz (hides it from students)")
    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        """Move a published quiz back to draft (hides it from students)."""
        quiz = self.get_object()
        quiz.is_published = False
        quiz.save(update_fields=["is_published"])
        return Response(
            QuizSerializer(quiz, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

@extend_schema_view(
    list=extend_schema(
        tags=["Questions"],
        summary="[Admin] List questions (filter by ?quiz=<id>)",
    ),
    retrieve=extend_schema(
        tags=["Questions"],
        summary="[Admin] Retrieve a single question",
    ),
    create=extend_schema(
        tags=["Questions"],
        summary="[Admin] Create a question",
    ),
    update=extend_schema(
        tags=["Questions"],
        summary="[Admin] Full update of a question",
    ),
    partial_update=extend_schema(
        tags=["Questions"],
        summary="[Admin] Partially update a question",
    ),
    destroy=extend_schema(
        tags=["Questions"],
        summary="[Admin] Delete a question",
    ),
)
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
