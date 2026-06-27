from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quizzes.models import Question, Quiz

from .models import Attempt, AttemptAnswer
from .serializers import (
    AttemptResultSerializer,
    LeaderboardEntrySerializer,
    MyAttemptSerializer,
    SubmitQuizSerializer,
)


class SubmitQuizView(APIView):
    """POST answers for a quiz, grade it, store the attempt (one per student)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, quiz_id):
        quiz = get_object_or_404(
            Quiz, pk=quiz_id, is_published=True, status=Quiz.Status.READY
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
