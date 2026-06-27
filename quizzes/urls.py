from rest_framework.routers import DefaultRouter

from .views import QuestionViewSet, QuizViewSet

router = DefaultRouter()
router.register("quizzes", QuizViewSet, basename="quiz")
router.register("questions", QuestionViewSet, basename="question")

urlpatterns = router.urls
