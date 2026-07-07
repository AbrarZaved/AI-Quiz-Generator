from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quizzes.models import Question, Quiz
from subscriptions.permissions import FREE_TRIAL_QUIZ_LIMIT

from .models import Attempt, AttemptAnswer
from .serializers import (
    AttemptResultSerializer,
    LeaderboardEntrySerializer,
    MyAttemptSerializer,
    SubmitQuizSerializer,
    RecentQuizUploadSerializer,
    TopStudentSerializer,
)
from django.contrib.auth import get_user_model
from django.db.models import (
    Avg,
    Case,
    Count,
    ExpressionWrapper,
    F,
    FloatField,
    Value,
    When,
)

from quizzes.permissions import IsAdminRole


@extend_schema(
    tags=["Attempts"],
    summary="Submit answers for a quiz and receive a graded result",
)
class SubmitQuizView(APIView):
    """POST answers for a quiz, grade it, store the attempt (one per student)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, quiz_id):
        quiz = get_object_or_404(
            Quiz, pk=quiz_id, is_published=True, status=Quiz.Status.READY
        )

        # Free-tier access check: only the first FREE_TRIAL_QUIZ_LIMIT quizzes
        # (ordered by creation date) are accessible without a premium subscription.
        user = request.user
        if not user.is_admin:
            sub = getattr(user, "subscription", None)
            is_premium = bool(sub and sub.is_premium)
            if not is_premium:
                free_ids = list(
                    Quiz.objects.filter(is_published=True, status=Quiz.Status.READY)
                    .order_by("created_at")
                    .values_list("id", flat=True)[:FREE_TRIAL_QUIZ_LIMIT]
                )
                if quiz.id not in free_ids:
                    return Response(
                        {
                            "detail": "A premium subscription is required to attempt this quiz."
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

        if Attempt.objects.filter(student=request.user, quiz=quiz).exists():
            return Response(
                {"detail": "You have already attempted this quiz."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = SubmitQuizSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Map submitted answers by question id.
        submitted = {
            a["question"]: a.get("selected_option")
            for a in serializer.validated_data["answers"]
        }

        questions = list(quiz.questions.all())
        question_ids = {q.id for q in questions}

        # Reject answers that don't belong to this quiz.
        unknown = set(submitted) - question_ids
        if unknown:
            return Response(
                {"detail": f"Unknown question ids for this quiz: {sorted(unknown)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            attempt = Attempt.objects.create(
                student=request.user, quiz=quiz, total=len(questions)
            )
            score = 0
            answer_rows = []
            for question in questions:
                selected = submitted.get(question.id)
                is_correct = selected == question.correct_answer
                if is_correct:
                    score += 1
                answer_rows.append(
                    AttemptAnswer(
                        attempt=attempt,
                        question=question,
                        selected_option=selected,
                        is_correct=is_correct,
                    )
                )
            AttemptAnswer.objects.bulk_create(answer_rows)
            attempt.score = score
            attempt.save(update_fields=["score"])

        attempt = (
            Attempt.objects.prefetch_related("answers__question")
            .select_related("quiz")
            .get(pk=attempt.pk)
        )
        return Response(
            AttemptResultSerializer(attempt).data, status=status.HTTP_201_CREATED
        )


@extend_schema(
    tags=["Attempts"],
    summary="Retrieve the current student's detailed result for a quiz",
)
class QuizResultView(APIView):
    """GET the current student's detailed result for a quiz."""

    permission_classes = [IsAuthenticated]

    def get(self, request, quiz_id):
        attempt = (
            Attempt.objects.prefetch_related("answers__question")
            .select_related("quiz")
            .filter(student=request.user, quiz_id=quiz_id)
            .first()
        )
        if attempt is None:
            return Response(
                {"detail": "You have not attempted this quiz yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(AttemptResultSerializer(attempt).data)


@extend_schema(
    tags=["Attempts"],
    summary="List all past quiz attempts for the current student",
)
class MyAttemptsView(generics.ListAPIView):
    """GET the current student's past quizzes + results."""

    permission_classes = [IsAuthenticated]
    serializer_class = MyAttemptSerializer

    def get_queryset(self):
        return (
            Attempt.objects.select_related("quiz")
            .filter(student=self.request.user)
            .order_by("-submitted_at")
        )


@extend_schema(
    tags=["Attempts"],
    summary="Get the ranked leaderboard for a specific quiz",
)
class LeaderboardView(APIView):
    """GET the leaderboard for a quiz (ranked by score, then time)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, pk=quiz_id)
        attempts = list(
            Attempt.objects.select_related("student")
            .filter(quiz=quiz)
            .order_by("-score", "submitted_at")
        )
        for index, attempt in enumerate(attempts, start=1):
            attempt.rank = index
        data = LeaderboardEntrySerializer(attempts, many=True).data
        return Response({"quiz": quiz.id, "quiz_title": quiz.title, "results": data})

User = get_user_model()


@extend_schema(
    tags=["Dashboard"],
    summary="[Admin] Aggregated stats for the dashboard overview screen",
)
class DashboardOverviewView(APIView):
    """GET aggregated data for the admin dashboard overview:

    * total student & quiz-upload counts
    * top students (by average score, then quizzes completed)
    * the most recent quiz uploads
    """

    permission_classes = [IsAdminRole]

    def get(self, request):
        top_limit = self._int_param(request, "top_students", default=6)
        recent_limit = self._int_param(request, "recent_uploads", default=6)

        total_students = User.objects.filter(role=User.Role.STUDENT).count()
        total_quiz_uploads = Quiz.objects.count()

        # Per-attempt percentage, guarding against total == 0.
        percentage_expr = Case(
            When(
                attempts__total__gt=0,
                then=ExpressionWrapper(
                    F("attempts__score") * 100.0 / F("attempts__total"),
                    output_field=FloatField(),
                ),
            ),
            default=Value(0.0),
            output_field=FloatField(),
        )

        top_students = (
            User.objects.filter(
                role=User.Role.STUDENT, attempts__isnull=False
            )
            .annotate(
                quizzes_completed=Count("attempts", distinct=True),
                average_score=Avg(percentage_expr),
            )
            .order_by("-average_score", "-quizzes_completed")[:top_limit]
        )

        top_rows = [
            {
                "student_id": student.id,
                "student_name": student.full_name,
                "average_score": round(student.average_score or 0.0, 2),
                "quizzes_completed": student.quizzes_completed,
            }
            for student in top_students
        ]

        recent_uploads = Quiz.objects.annotate(
            questions_total=Count("questions")
        ).order_by("-created_at")[:recent_limit]

        data = {
            "total_students": total_students,
            "total_quiz_uploads": total_quiz_uploads,
            "top_students": TopStudentSerializer(top_rows, many=True).data,
            "recent_uploads": RecentQuizUploadSerializer(
                recent_uploads, many=True
            ).data,
        }
        return Response(data)

    @staticmethod
    def _int_param(request, name, default):
        """Parse a positive int query param, clamped to a sane range."""
        try:
            value = int(request.query_params.get(name, default))
        except (TypeError, ValueError):
            return default
        return max(1, min(value, 50))