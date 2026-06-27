from django.urls import path

from .views import (
    LeaderboardView,
    MyAttemptsView,
    QuizResultView,
    SubmitQuizView,
)

urlpatterns = [
    path("quizzes/<int:quiz_id>/submit/", SubmitQuizView.as_view(), name="quiz-submit"),
    path(
        "quizzes/<int:quiz_id>/leaderboard/",
        LeaderboardView.as_view(),
        name="quiz-leaderboard",
    ),
    path(
        "quizzes/<int:quiz_id>/result/",
        QuizResultView.as_view(),
        name="quiz-result",
    ),
    path("me/attempts/", MyAttemptsView.as_view(), name="my-attempts"),
]
